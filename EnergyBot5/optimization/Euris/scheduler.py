from __future__ import annotations
from dataclasses import dataclass
import random
import math
import joblib
import numpy as np
from pathlib import Path
from typing import Dict, List, Optional

# ───────────────────────────────
# 1. Core data structures
# ───────────────────────────────
@dataclass
class Activity:
    # Rappresenta una singola attività da schedulare.
    id: str                 # Identificatore unico dell'attività
    duration: int           # Durata in slot (ogni slot dura 5 minuti)
    earliest: int           # Slot più "precoce" in cui può iniziare
    latest: int             # Ultimo slot in cui può iniziare
    power_kw: float         # Potenza (in kW) richiesta durante la durata
    employees: int          # Numero di dipendenti richiesti
    machines: List[str]     # Lista di ID dei macchinari necessari

class Instance:
    """Carica una istanza di scheduling dal JSON (come dict)."""
    def __init__(self, data: dict):
        # --- 1. Impostazione degli slot temporali ---
        # Legge la discretizzazione temporale dal dizionario.
        self.delta_min = data['delta_minutes']
        # Solo slot di 5 minuti sono supportati in questo modello.
        if self.delta_min != 5:
            raise Exception("Solo slot da 5 minuti supportati.")

        # Calcola il numero totale di slot in base alle ore dell'orizzonte.
        self.H = data['T_hours'] * (60 // self.delta_min)

        # --- 2. Gestione dei prezzi dell'energia ---
        # Recupera la lista dei prezzi (per kWh) dal dict.
        prezzi = data.get('prices_eur_per_kwh', [0.0])
        if len(prezzi) == 24:
            # Se la lista contiene 24 prezzi (uno per ogni ora), 
            # li espande a 288 slot (ogni ora 12 slot da 5 minuti)
            prezzi_estesi = []
            for price in prezzi:
                prezzi_estesi += [price] * 12   # Ripeti ogni prezzo 12 volte (12 slot per ora)
            prezzi = prezzi_estesi
        elif len(prezzi) == 1:
            # Se invece c'è solo un prezzo, lo replica per tutta la giornata
            prezzi = prezzi * self.H

        # Converte la lista in un array numpy per efficienza nei calcoli successivi
        self.prices = np.array(prezzi[:self.H], dtype=float)

        # --- 3. Capacità dipendenti ---
        # Può essere un numero fisso o una lista diversa per ogni slot
        emp = data.get('employees_per_slot', 9999)
        if type(emp) is list:
            # Se è una lista, la ripete finché non raggiunge H elementi
            emp_list = []
            while len(emp_list) < self.H:
                emp_list += emp
            # Si assicura che la lista abbia esattamente H elementi (taglia l'eccesso)
            emp_list = emp_list[:self.H]
            self.emp_cap = np.array(emp_list, dtype=int)
        else:
            # Se è un numero fisso, crea un array lungo H tutto uguale
            self.emp_cap = np.array([int(emp)] * self.H, dtype=int)

        # --- 4. Macchinari e potenza ---
        # Prepara un dizionario che mappa ogni macchinario al suo consumo di potenza
        self.machine_power = {}
        for m in data.get('machines', []):
            machine_id = m['id']                 # ID del macchinario
            power = m.get('power_kw', 0.0)       # Potenza (default 0.0 se mancante)
            self.machine_power[machine_id] = power

        # --- 5. Creazione delle attività ---
        # Costruisce oggetti Activity per ogni attività nella lista
        self.activities = {}
        for a in data['activities']:
            act = Activity(
                id=a['id'],
                duration=a['duration_slots'],
                earliest=a['earliest_start_slot'],
                latest=a['latest_start_slot'],
                power_kw=a['power_kw'],
                employees=a['employees'],
                machines=a['machines']
            )
            self.activities[a['id']] = act

        # --- 6. Precedenze tra attività ---
        # Per ogni attività, prepara una lista dei suoi predecessori (chi deve venire prima)
        self.preds = {}
        for aid in self.activities:
            self.preds[aid] = []   # All'inizio, nessun predecessore

        # Aggiunge i predecessori dalle relazioni di precedenza presenti nei dati
        for p in data.get('precedences', []):
            pred, succ = p           # pred: attività che deve essere prima, succ: attività successiva
            self.preds[succ].append(pred)

        # --- 7. Obiettivo dell'ottimizzazione ---
        # Può essere 'energy_cost' (minimizza il costo totale) o 'peak_power' (minimizza il picco massimo)
        self.objective = data.get('objective', 'energy_cost')
        if self.objective not in ['energy_cost', 'peak_power']:
            raise Exception('Obiettivo deve essere energy_cost oppure peak_power.')

# ───────────────────────────────
# 2. Scheduler
# ───────────────────────────────
class Scheduler:
 
    def __init__(self, inst, model_path=None):
        # Salva l'istanza (dati e vincoli)
        self.I = inst
        # Numero totale di slot (es. 24h -> 288 slot da 5')
        self.H = inst.H
        # Prova a caricare il modello ML se il percorso esiste
        self.model = None
        if model_path is not None and Path(model_path).exists():
            self.model = joblib.load(model_path)

        # Inizializza lo stato interno del scheduler
        self._init_state()

    def _init_state(self):
        """
        Prepara le strutture vuote per uno scheduling nuovo:
        - schedule: dizionario job_id -> slot di inizio
        - load_kw: potenza usata per ciascuno slot
        - load_emp: dipendenti occupati per slot
        - load_mach: dizionario macchina -> array booleano per occupazione
        - price_cs: somma cumulativa dei costi per calcolare velocemente i costi di un intervallo
        """
        # Mappa job_id -> inizio
        self.schedule = {}
        # Potenza per slot, inizialmente zero
        self.load_kw = np.zeros(self.H)
        # Dipendenti usati per slot, inizialmente zero
        self.load_emp = np.zeros(self.H, dtype=int)
        # Stato occupazione per ogni macchina e slot
        self.load_mach = {}
        # Per ogni macchina presente nell'istanza, crea un array di False
        for machine_id in self.I.machine_power:
            self.load_mach[machine_id] = np.zeros(self.H, dtype=bool)

        # Calcola array cumulativo dei costi: price_cs[t] = costo totale da 0 fino a t
        slot_hours = self.I.delta_min / 60.0
        # Array di lunghezza H+1 per includere 0
        self.price_cs = np.zeros(self.H + 1)
        total = 0.0
        self.price_cs[0] = 0.0
        # Riempie price_cs con la somma cumulativa dei costi
        for t in range(self.H):
            total = total + self.I.prices[t] * slot_hours
            self.price_cs[t + 1] = total

    def run(self, improve=True, max_iter=500, restarts=5, seed=0):
        """
        Lancia lo scheduler:
        - Se esiste il modello ML: start ML + miglioramento
        - Altrimenti: greedy casuale con multi-start
        Restituisce (schedule, valore obiettivo)
        """
        # Caso con ML
        if self.model is not None:
            random.seed(seed)
            self._init_state()
            self._ml_greedy()
            if improve:
                self._local_search(max_iter)
            # Copia lo schedule e calcola l'obiettivo
            final_schedule = dict(self.schedule)
            final_obj = self._objective()
            return final_schedule, final_obj

        # Caso greedy casuale con più restart
        best_schedule = None
        best_value = float('inf')
        for r in range(restarts):
            random.seed(seed + r)
            self._init_state()
            self._random_greedy()
            if improve:
                self._local_search(max_iter)
            current_value = self._objective()
            # Se miglioriamo, salviamo questo
            if current_value < best_value:
                best_value = current_value
                best_schedule = dict(self.schedule)

        # Alla fine, ricreiamo lo stato migliore
        self._init_state()
        # Applichiamo il miglior schedule trovato
        for job_id, start in best_schedule.items():
            job = self.I.activities[job_id]
            self._commit(job, start)

        return best_schedule, best_value

    def _ml_greedy(self):
        """
        Greedy basato sul ranking fornito dal modello ML.
        Costruisce feature per ogni job, predice un punteggio,
        quindi piazza i job in ordine di punteggio (dal più alto).
        """
        # Prepara feature e lista di ID
        features = []
        job_ids = []
        num_jobs = len(self.I.activities)
        # Costruiamo le feature manualmente
        for job_id, job in self.I.activities.items():
            # Calcolo del prezzo medio nell'intervallo ammesso
            if self.I.objective == 'energy_cost':
                price_slice = self.I.prices[job.earliest : job.latest]
                avg_price = sum(price_slice) / len(price_slice)
            else:
                avg_price = 0.0

            # Feature semplificate: [num_jobs, durata, earliest, latest,...]
            feat = [
                num_jobs,
                job.duration,
                job.earliest,
                job.latest,
                job.power_kw,
                job.employees,
                len(self.I.preds[job_id]),      # numero di predecessori
                job.latest - job.earliest,       # ampiezza finestra
                avg_price
            ]
            features.append(feat)
            job_ids.append(job_id)

        # Predice punteggi ML
        scores = self.model.predict(np.array(features))
        # Unisce score e id, ordina per score decrescente
        scored_jobs = list(zip(scores, job_ids))
        scored_jobs_sorted = sorted(scored_jobs, key=lambda x: x[0], reverse=True)

        # Piazza i job in ordine di punteggio
        for score, job_id in scored_jobs_sorted:
            job = self.I.activities[job_id]
            best_cost = float('inf')
            best_start = None
            # Prova ogni possibile inizio
            for start in range(job.earliest, job.latest + 1):
                end = start + job.duration
                # Controlla che non superi orizzonte
                if end > self.H:
                    continue
                # Verifica se è fattibile
                if self._feasible(job, start):
                    cost = self._placement_score(job, start)
                    if cost < best_cost:
                        best_cost = cost
                        best_start = start

            # Se abbiamo trovato una posizione valida, la assegniamo
            if best_start is not None:
                self._commit(job, best_start)

    def _random_greedy(self):
        """
        Greedy topologico casuale:
        - Calcola ordine topologico sulle precedenze
        - Sceglie casualmente tra i job ready
        - Piaza ciascun job al costo minimo
        """
        # Conteggia quanti pred ha ogni job
        indegree = {}
        for job_id, preds in self.I.preds.items():
            indegree[job_id] = len(preds)

        # Inizializza lista ready con quelli a indegree=0
        ready = []
        for job_id, deg in indegree.items():
            if deg == 0:
                ready.append(job_id)

        topo_order = []  # conterrà l'ordine topologico
        # Costruiamo ordine topologico
        while len(ready) > 0:
            # Prendo un job a caso tra quelli pronti
            choice = random.choice(ready)
            # Lo tolgo da ready
            ready.remove(choice)
            topo_order.append(choice)
            # Riduco indegree dei successori
            for succ_id, preds in self.I.preds.items():
                # Se choice è pred di succ_id
                if choice in preds:
                    indegree[succ_id] = indegree[succ_id] - 1
                    # Se ora è zero, aggiungo a ready
                    if indegree[succ_id] == 0:
                        ready.append(succ_id)

        # Se topo_order incompleto, c'è un ciclo
        if len(topo_order) < len(self.I.activities):
            raise Exception("Cycle detected in precedences")

        # Piazza i job in topo_order
        for job_id in topo_order:
            job = self.I.activities[job_id]
            candidates = []
            # Trova tutti gli start fattibili
            for start in range(job.earliest, job.latest + 1):
                end = start + job.duration
                if end <= self.H and self._feasible(job, start):
                    candidates.append(start)

            # Se non ci sono start validi, skippo
            if len(candidates) == 0:
                continue

            # Calcolo punteggio per ogni candidato e scelgo il migliore
            best_start = None
            best_score = float('inf')
            for start in candidates:
                score = self._placement_score(job, start)
                # Aggiungo piccola casualità per variare
                score = score + random.random() * 0.001
                if score < best_score:
                    best_score = score
                    best_start = start

            # Commit della scelta
            if best_start is not None:
                self._commit(job, best_start)

    def _local_search(self, max_iter):
        """
        Miglioramento locale (simulated annealing):
        - Ogni iterazione faccio shift o swap casuale
        - Accetto mosse peggiori con probabilità decrescente
        """
        # Temperatura iniziale e fattore di raffreddamento
        T = 1.0
        alpha = 0.95
        # Lista degli job già piazzati
        job_list = list(self.schedule.keys())

        for i in range(max_iter):
            r = random.random()
            if r < 0.5:
                # Shift: sposto un job avanti o indietro di 1 slot
                job_id = random.choice(job_list)
                job = self.I.activities[job_id]
                old_start = self.schedule[job_id]
                # Direzione casuale
                dir_choice = random.choice([-1, 1])
                new_start = old_start + dir_choice
                end_new = new_start + job.duration

                # Controlla semplicità e fattibilità
                if new_start >= job.earliest and end_new <= self.H:
                    if self._feasible(job, new_start, exclude=job_id):
                        # Applico lo shift
                        self._uncommit(job, old_start)
                        self._commit(job, new_start)
                        # Calcolo delta obiettivo
                        old_score = self._placement_score(job, old_start)
                        new_score = self._placement_score(job, new_start)
                        delta = new_score - old_score
                        # Se peggiore, potrei rifiutare
                        if delta > 0:
                            prob = math.exp(-delta / T)
                            if random.random() > prob:
                                # Ripristino
                                self._uncommit(job, new_start)
                                self._commit(job, old_start)
                # Raffreddo temperatura
                T = T * alpha
            else:
                # Swap: scambio due job
                job1, job2 = random.sample(job_list, 2)
                j1 = self.I.activities[job1]
                j2 = self.I.activities[job2]
                s1 = self.schedule[job1]
                s2 = self.schedule[job2]

                # Provo a scambiare e vedo se fattibile
                ok = self.try_swap(job1, job2)
                if ok:
                    # Se OK, calcolo delta e potrei revert
                    new_score1 = self._placement_score(j1, self.schedule[job1])
                    new_score2 = self._placement_score(j2, self.schedule[job2])
                    old_score1 = self._placement_score(j1, s1)
                    old_score2 = self._placement_score(j2, s2)
                    delta = (new_score1 + new_score2) - (old_score1 + old_score2)
                    if delta > 0:
                        prob = math.exp(-delta / T)
                        if random.random() > prob:
                            # Revert swap
                            self.try_swap(job1, job2)
                # Raffreddo temperatura
                T = T * alpha

    def _feasible(self, job, start, exclude=None):
        """
        Controlla se è possibile piazzare `job` a `start`:
        - dentro la finestra
        - senza superare H
        - dipendenti
        - macchine libere
        - precedenze rispettate
        `exclude` serve per ignorare un job durante lo spostamento
        """
        # Finestra temporale
        if start < job.earliest or start > job.latest:
            return False
        end = start + job.duration
        if end > self.H:
            return False

        # Dipendenti
        for t in range(start, end):
            if self.load_emp[t] + job.employees > self.I.emp_cap[t]:
                return False

        # Macchine
        for m in job.machines:
            for t in range(start, end):
                if self.load_mach[m][t]:
                    return False

        # Precedenze
        for pred in self.I.preds[job.id]:
            if pred == exclude:
                continue
            if pred not in self.schedule:
                return False
            pred_end = self.schedule[pred] + self.I.activities[pred].duration
            if start < pred_end:
                return False

        return True

    def _commit(self, job, start):
        """Piazza `job` a `start` aggiornando carichi e schedule."""
        end = start + job.duration
        self.schedule[job.id] = start
        for t in range(start, end):
            self.load_kw[t] += job.power_kw
            self.load_emp[t] += job.employees
            for m in job.machines:
                self.load_mach[m][t] = True

    def _uncommit(self, job, start):
        """Rimuove `job` da `start`, ripristinando i carichi."""
        end = start + job.duration
        for t in range(start, end):
            self.load_kw[t] -= job.power_kw
            self.load_emp[t] -= job.employees
            for m in job.machines:
                self.load_mach[m][t] = False

    def _placement_score(self, job, start):
        """Calcola il costo o picco se `job` fosse a `start`."""
        end = start + job.duration
        if self.I.objective == 'energy_cost':
            # Costo energia = potenza * differenza cumulativa prezzi
            return job.power_kw * (self.price_cs[end] - self.price_cs[start])
        else:
            # Picco di potenza massimo
            peak = 0.0
            for t in range(start, end):
                val = self.load_kw[t] + job.power_kw
                if val > peak:
                    peak = val
            return peak

    def _objective(self):
        """Valuta lo schedule corrente: costo totale o picco"""
        if self.I.objective == 'energy_cost':
            total = 0.0
            # calcolo costo totale: somma potenza*prezzo*ore
            for t in range(self.H):
                total += self.load_kw[t] * self.I.prices[t] * (self.I.delta_min / 60)
            return total
        else:
            # Picco: valore massimo in load_kw
            max_val = 0.0
            for t in range(self.H):
                if self.load_kw[t] > max_val:
                    max_val = self.load_kw[t]
            return max_val

    def try_shift(self, job_id, direction):
        """Prova a spostare un job avanti/indietro. Ritorna True se avvenuto."""
        job = self.I.activities[job_id]
        old_start = self.schedule[job_id]
        new_start = old_start + direction
        end = new_start + job.duration
        # Verifica semplice di windows
        if new_start < job.earliest or end > self.H:
            return False
        if self._feasible(job, new_start, exclude=job_id):
            self._uncommit(job, old_start)
            self._commit(job, new_start)
            return True
        return False

    def try_swap(self, job_id1, job_id2):
        """Prova a scambiare start di due job. Ritorna True se fatto."""
        job1 = self.I.activities[job_id1]
        job2 = self.I.activities[job_id2]
        s1 = self.schedule[job_id1]
        s2 = self.schedule[job_id2]
        # Rimuovo entrambi
        self._uncommit(job1, s1)
        self._uncommit(job2, s2)
        # Verifico feasibility incrociata
        ok1 = self._feasible(job1, s2, exclude=job_id1)
        ok2 = self._feasible(job2, s1, exclude=job_id2)
        if ok1 and ok2:
            # Applico swap
            self._commit(job1, s2)
            self._commit(job2, s1)
            return True
        # Ripristino se fallisce
        self._commit(job1, s1)
        self._commit(job2, s2)
        return False
