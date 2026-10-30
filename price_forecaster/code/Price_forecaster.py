#Decide which models to train between ['XGBoost','NBEATS','NHITS']. When value is not correct, NHITS will be used as model
models_to_run=['NHITS']
# models_to_run=['NHITS','NBEATS','XGBoost']


from pathlib import Path
FORECASTER_ROOT = Path(__file__).resolve().parents[1]
dataset_folder = str(FORECASTER_ROOT / 'datasets_folder')
filepath_gui_energy_prices = 'GUI_ENERGY_PRICES'
filepath_innothon_consumption_dataset = 'Estrazione consumi orari Innothon.xlsx'
models_path=str(FORECASTER_ROOT / 'models')

#Path of the required datasets
import os
datasets_path={
    'price' :     os.path.join(dataset_folder,'Prices_dataset.csv'),
    'consumption':    os.path.join(dataset_folder,'Consumi_Orari_2024.csv'),
    'weather':  os.path.join(dataset_folder,'Weather_2024_2025.csv'),}

#it can be 24, 24*7, 24*30
n_out=24*7

# XGBoost parameters
xgb_params = {
    'num_target': n_out,           # Number of output targets (e.g., forecast horizon)
    'n_estimators': 200,           # Total number of boosting trees (iterations)
    'learning_rate': 0.1,          # Step size shrinkage controlling how much each tree contributes
    'max_depth': 8,               # Maximum depth of each tree (controls model complexity)
    'gamma': 0.1,                  # Minimum loss reduction required to make a further partition (regularization)
    'subsample': 0.9,              # Fraction of samples used per tree (prevents overfitting)
    'colsample_bytree': 0.4,       # Fraction of features used per tree
    'colsample_bylevel': 0.8,      # Fraction of features used per level
    'colsample_bynode': 0.8,       # Fraction of features used per split
    'lambda': 1.6,                 # L2 regularization term on weights (ridge penalty)
    'alpha': 0.2,                  # L1 regularization term on weights (lasso penalty)
    'random_state': 42,            # Reproducibility seed for deterministic results
}


# NBEATS parameters
nbeats_params = {
    'n_in': 24*7,                  # Input window length (e.g., one week of hourly data)
    'n_out': n_out,                # Output horizon (forecast length)
    'step': 1,                     # Stride between consecutive training samples
    'n_blocks': 4,                 # Number of blocks per stack
    'n_layers': 2,                 # Number of fully-connected layers within each block
    'layer_width': 512,             # Number of neurons per hidden layer
    'dropout_rate': 0.1,           # Dropout for regularization
    'learning_rate': 0.00003,       # Optimizer learning rate
    'seasonality_period': 168,     # Main seasonality cycle (e.g., weekly = 168 hours)
    'n_harmonics': 12,              # Number of harmonics for seasonality modeling
    'theta_dim': 12,                # Dimensionality of the basis expansion for trend modeling (controls forecast flexibility)
    'stack_types': [
        'trend', 
        'seasonality', 
        'generic'],                # Types of stacks capturing different components
    'epochs': 50,                  # Number of training epochs
    'batch_size': 16,              # Mini-batch size during training
}

# NHITS parameters
nhits_params = {
    'n_in': 24*7,                    # Input window length (e.g., one week of hourly data)
    'n_out': n_out,                  # Forecast horizon (number of output steps)
    'step' :1,                       # Stride between training samples
    'n_blocks': 
        [5, 3, 3, 2, 2, 2, 2],       # Number of blocks per hierarchical level
    'mlp_units': 
        [512],               # Hidden layer sizes in the block’s MLPs
    'pool_kernel_sizes': 
        [168, 48, 24, 12, 4, 2, 1],  # Downsampling window sizes per level (multi-resolution)
    'n_freq_downsample': 
        [ 48, 24, 12,  4, 2, 1, 1],  # Frequency downsampling ratios per level
    'dropout_rate': 0.1,             # Dropout probability for regularization
    'learning_rate': 0.00003,        # Optimizer learning rate
    'epochs': 100,                    # Number of training epochs
    'batch_size': 16,                # Mini-batch size
    'activation': 'relu',            # Activation function in MLPs
    }

  

#number of next days windows plots (if value n_out is 24, it'll plot next 7 days predictions)
n_windows_to_plot_xgboost=24*7//xgb_params['num_target']*2
n_windows_to_plot_nhits=24*7//nhits_params['n_out']*2
n_windows_to_plot_nbeats=24*7//nbeats_params['n_out']*2
for n in [n_windows_to_plot_nbeats, n_windows_to_plot_xgboost, n_windows_to_plot_nhits]:
    if n==0:
        n=1

#X and y sizes in %
skip_size=0.0         #starting point of train set. If 0, use all dataset
train_size=0.8     
val_size=0.1      
test_size=0.1      


#datasets to merge
merge_consumptions_data_bool=False
merge_weather_data_bool=False

#features to add (when  xgboost, add_price_features_bool is True by default)
add_price_features_bool=False
add_consumption_features_bool=False
add_weather_features_bool=False
add_temporal_features_bool=False
add_cross_features_bool=False



import torch
from torch.cuda import is_available
# additional parameters for xgboost
if is_available():
    xgb_params['tree_method'] = 'gpu_hist'
    xgb_params['predictor'] = 'gpu_predictor'
else:
    xgb_params['tree_method'] = 'hist'
    xgb_params['predictor'] = 'cpu_predictor'



results = {}
scenarios = []




import pandas as pd
import numpy as np
import time
import mplcursors
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pickle
import importlib
import xgboost as xgb
import shap
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import mean_squared_error, mean_absolute_error
from glob import glob
import warnings
warnings.filterwarnings('ignore')
import warnings
import re
from math import log
from decimal import InvalidOperation
import openmeteo_requests
import requests_cache
from retry_requests import retry
from scipy import stats


class PredictionIntervals:
    """Utility class for calculating and plotting prediction intervals"""
    
    @staticmethod
    def calculate_intervals(y_true, y_pred, confidence_levels=[0.8, 0.9]):
        """
        Calculate prediction intervals based on residuals:
        y_true: actual values (samples, horizons)
        y_pred: predicted values (samples, horizons)
        confidence_levels: list of confidence levels (e.g., [0.8, 0.9])

        """
        residuals = y_true - y_pred
        
        # Calculate standard deviation of residuals per horizon
        if len(y_true.shape) == 2:
            std_residuals = np.std(residuals, axis=0)
        else:
            std_residuals = np.std(residuals)
        
        intervals = {}
        for conf_level in confidence_levels:
            # Calculate z-score for confidence level
            alpha = 1 - conf_level
            z_score = stats.norm.ppf(1 - alpha/2)
            
            # Calculate bounds
            margin = z_score * std_residuals
            intervals[conf_level] = {'lower': y_pred - margin,'upper': y_pred + margin,'margin': margin}
        
        return intervals
    
    @staticmethod
    def calculate_quantile_intervals(y_true, y_pred, quantiles=[0.1, 0.05]):
        """
        Calculate prediction intervals using quantiles of residuals:
        y_true: actual values
        y_pred: predicted values  
        quantiles: lower quantiles (e.g., [0.1, 0.05] for 80% and 90%)
        """
        residuals = y_true - y_pred
        
        intervals = {}
        for q in quantiles:
            conf_level = 1 - 2*q
            
            if len(y_true.shape) == 2:
                lower_q = np.quantile(residuals, q, axis=0)
                upper_q = np.quantile(residuals, 1-q, axis=0)
            else:
                lower_q = np.quantile(residuals, q)
                upper_q = np.quantile(residuals, 1-q)
            
            intervals[conf_level] = {
                'lower': y_pred + lower_q,
                'upper': y_pred + upper_q
            }
        
        return intervals


def plot_predictions_with_intervals(forecaster, y_true, y_pred, dates, model_name, ax=None, horizon_to_plot=0, confidence_levels=[0.8, 0.9],use_quantiles=False):
    """
    Enhanced plot with confidence/prediction intervals:
    forecaster: PriceForecaster instance
    y_true: actual values
    y_pred: predicted values
    dates: date array
    model_name: name of the model
    ax: matplotlib axis
    horizon_to_plot: which horizon to plot (for multi-output)
    confidence_levels: list of confidence levels (e.g., [0.8, 0.9])
    use_quantiles: if True, use quantile-based intervals instead of normal-based
    """
    if ax is None:
        fig, ax = plt.subplots(figsize=(15, 8))
    
    # Calculate intervals
    if use_quantiles:
        quantiles = [(1-cl)/2 for cl in confidence_levels]
        intervals = PredictionIntervals.calculate_quantile_intervals(y_true, y_pred, quantiles=quantiles)
    else:
        intervals = PredictionIntervals.calculate_intervals(y_true, y_pred, confidence_levels=confidence_levels)
    
    # Handle multi-output
    if len(y_true.shape) == 2 and y_true.shape[1] > 1:
        if len(dates) != len(y_true):
            dates_plot = dates[:len(y_true)]
        else:
            dates_plot = dates
        
        y_true_plot = y_true[:, horizon_to_plot]
        y_pred_plot = y_pred[:, horizon_to_plot]
        
        # Plot main lines
        ax.plot(dates_plot, y_true_plot, label='Actual', color='blue', alpha=0.8, linewidth=2, zorder=3)
        ax.plot(dates_plot, y_pred_plot, label='Predicted', color='red', alpha=0.8, linewidth=2, zorder=3)
        
        # Plot intervals
        colors = ['yellow', 'orange']
        alphas = [0.3, 0.2]
        
        for i, (conf_level, color, alpha) in enumerate(zip(
            sorted(confidence_levels, reverse=True), colors, alphas)):
            
            lower = intervals[conf_level]['lower'][:, horizon_to_plot]
            upper = intervals[conf_level]['upper'][:, horizon_to_plot]
            
            ax.fill_between(dates_plot, lower, upper, color=color, alpha=alpha, label=f'{int(conf_level*100)}% Interval',zorder=1+i)
    
    else:
        # Single output case
        ax.plot(dates, y_true, label='Actual', color='blue', alpha=0.8, linewidth=2, zorder=3)
        ax.plot(dates, y_pred, label='Predicted', color='red', alpha=0.8, linewidth=2, zorder=3)
        
        colors = ['yellow', 'orange']
        alphas = [0.3, 0.2]
        
        for i, (conf_level, color, alpha) in enumerate(zip(sorted(confidence_levels, reverse=True), colors, alphas)):
            
            lower = intervals[conf_level]['lower']
            upper = intervals[conf_level]['upper']
            
            ax.fill_between(dates, lower, upper, color=color, alpha=alpha,label=f'{int(conf_level*100)}% Interval',zorder=1+i)
    
    ax.set_title(f'{model_name} - Predictions with Confidence Intervals')
    ax.set_xlabel('Date')
    ax.set_ylabel('Energy Price (€/MWh)')
    ax.legend(loc='best')
    ax.grid(True, alpha=0.3)
    plt.xticks(rotation=45)
    plt.tight_layout()
    
    return ax


def plot_prediction_sequences_with_intervals(forecaster, y_true, y_pred, dates, model_name, window=24, n_sequences=5,confidence_levels=[0.8, 0.9],use_quantiles=False):
    """
    Plot complete prediction sequences with confidence intervals
    """
    if use_quantiles:
        quantiles = [(1-cl)/2 for cl in confidence_levels]
        intervals = PredictionIntervals.calculate_quantile_intervals(y_true, y_pred, quantiles=quantiles)
    else:
        intervals = PredictionIntervals.calculate_intervals(y_true, y_pred, confidence_levels=confidence_levels)
    
    if window == 24:
        if n_sequences > 7:
            n_sequences = 7
        fig, axes = plt.subplots(n_sequences//2 + n_sequences%2, 2, figsize=(15, 3*n_sequences))
        n_sequences = n_sequences + n_sequences%2
        axes = axes.flatten()
    else:
        if n_sequences > 2:
            n_sequences = 2
        fig, axes = plt.subplots(n_sequences, figsize=(15, 4*n_sequences))
    
    if n_sequences == 1:
        axes = [axes]
    
    colors = ['yellow', 'orange']
    alphas = [0.3, 0.2]
    
    for i in range(n_sequences):
        ax = axes[i]
        sequence_idx = i * window
        
        hours = np.arange(1, window + 1)
        
        # Plot intervals first (background)
        for j, (conf_level, color, alpha) in enumerate(zip(
            sorted(confidence_levels, reverse=True), colors, alphas)):
            
            lower = intervals[conf_level]['lower'][sequence_idx, :]
            upper = intervals[conf_level]['upper'][sequence_idx, :]
            
            ax.fill_between(hours, lower, upper, color=color, alpha=alpha,label=f'{int(conf_level*100)}% Interval' if i==0 else '',zorder=1+j)
        
        # Plot actual and predicted
        ax.plot(hours, y_true[sequence_idx, :], 'o-', label='Actual', color='blue', alpha=0.8, linewidth=2, markersize=4, zorder=3)
        ax.plot(hours, y_pred[sequence_idx, :], 's-', label='Predicted', color='red', alpha=0.8, linewidth=2, markersize=4, zorder=3)
        
        sequence_date = dates[sequence_idx] if sequence_idx < len(dates) else f"Sequence {i+1}"
        ax.set_title(f'{model_name} - {window}h Prediction starting {sequence_date}')
        ax.set_xlabel('Hours Ahead')
        ax.set_ylabel('Energy Price (€/MWh)')
        
        if i == 0:
            ax.legend(loc='best')
        
        ax.grid(True, alpha=0.3)
        ax.set_xticks(range(1, window + 1, 2))
    
    plt.tight_layout()
    plt.show()


def plot_interval_coverage(forecaster, y_true, y_pred, model_name, confidence_levels=[0.8, 0.9],use_quantiles=False):
    """
    Plot the coverage of prediction intervals per horizon
    Shows how often the actual values fall within the predicted intervals
    """
    if use_quantiles:
        quantiles = [(1-cl)/2 for cl in confidence_levels]
        intervals = PredictionIntervals.calculate_quantile_intervals(y_true, y_pred, quantiles=quantiles)
    else:
        intervals = PredictionIntervals.calculate_intervals(y_true, y_pred, confidence_levels=confidence_levels)
    
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6))
    
    # Per-horizon coverage
    if len(y_true.shape) == 2:
        n_horizons = y_true.shape[1]
        horizons = np.arange(1, n_horizons + 1)
        
        for conf_level in confidence_levels:
            lower = intervals[conf_level]['lower']
            upper = intervals[conf_level]['upper']
            
            # Check if actual values fall within interval
            within_interval = (y_true >= lower) & (y_true <= upper)
            coverage = np.mean(within_interval, axis=0) * 100
            
            ax1.plot(horizons, coverage, 'o-', label=f'{int(conf_level*100)}% Interval',linewidth=2, markersize=5)
            ax1.axhline(conf_level * 100, linestyle='--', alpha=0.5, label=f'Target {int(conf_level*100)}%')
        
        ax1.set_xlabel('Horizon (Hours Ahead)')
        ax1.set_ylabel('Coverage (%)')
        ax1.set_title(f'{model_name} - Interval Coverage by Horizon')
        ax1.legend()
        ax1.grid(True, alpha=0.3)
        ax1.set_ylim([0, 105])
    
    # Overall coverage bar chart
    for conf_level in confidence_levels:
        lower = intervals[conf_level]['lower']
        upper = intervals[conf_level]['upper']
        
        within_interval = (y_true >= lower) & (y_true <= upper)
        overall_coverage = np.mean(within_interval) * 100
        
        ax2.bar(f'{int(conf_level*100)}%', overall_coverage, 
               alpha=0.7, label=f'Actual: {overall_coverage:.1f}%')
        ax2.axhline(conf_level * 100, linestyle='--', color='red', alpha=0.5)
    
    ax2.set_ylabel('Coverage (%)')
    ax2.set_title(f'{model_name} - Overall Interval Coverage')
    ax2.legend()
    ax2.grid(True, alpha=0.3, axis='y')
    ax2.set_ylim([0, 105])
    
    plt.tight_layout()
    plt.show()


def add_interval_methods_to_forecaster():
    """
    Add interval plotting methods to PriceForecaster class.
    Call this function after the class definition.
    """
    PriceForecaster.plot_predictions_with_intervals = plot_predictions_with_intervals
    PriceForecaster.plot_prediction_sequences_with_intervals = plot_prediction_sequences_with_intervals
    PriceForecaster.plot_interval_coverage = plot_interval_coverage


class CreateDatasets:
    def __init__(self):
        self.df_price= None
        self.df_weather= None
        self.df_consumption= None


    def get_energy_consumption_data(self,final_name=datasets_path['consumption'],filepath=os.path.join(dataset_folder, filepath_innothon_consumption_dataset)):
        # Load only the relevant sheet
        df = pd.read_excel(filepath, sheet_name='estrazione_consumi_orari')


        def plot_consumption_data(df):
            fig, axes = plt.subplots(12, figsize=(20, 25))
            window_length = 8
            plt.figure(figsize=(15, 8))
            for i in range(4):
                for j, city in enumerate(["Milano", "Roma", "Napoli"]):
                    # Plot valori reali
                    print(f'plot-{i * 3 + j}, {i}-{city}')
                    axes[i * 3 + j].plot(df["ds"].iloc[96 * window_length:96 * (window_length + 1)],
                                        df[f"consumption_{i}_{city}"].iloc[96 * window_length:96 * (window_length + 1)],
                                        label='consumption', color='blue', linewidth=2, alpha=0.8)
                    axes[i * 3 + j].set_xlabel = 'ds'
                    axes[i * 3 + j].set_ylabel(f'consumption-{i}-{city}')
                    axes[i * 3 + j].set_title('Performance Ensemble per Fold')
                    axes[i * 3 + j].legend()
                    axes[i * 3 + j].grid(True, alpha=0.3)
            plt.show()

            print('Data after interpolation')
            print(df.head(4))

        def interpolate_consumption_data(df_consumption):
            df = df_consumption.copy()
            for seg in range(4):
                for j, city in enumerate(["Milano", "Roma", "Napoli"]):
                    col = f"consumption_{seg}_{city}"
                    series = df_consumption[col].copy()

                    # Rolling mean
                    rolling_mean = series.rolling(8, center=True, min_periods=3).mean()
                    rolling_order = np.log10(rolling_mean)

                    def fix_scale_with_rolling(val, ref_order):
                        if pd.isna(val) or pd.isna(ref_order):
                            return val
                        val_order = np.log10(val)
                        diff = ref_order - val_order
                        if 1 <= diff <= 3:
                            return val * (10 ** diff)
                        elif -3 <= diff <= -1:
                            return val / (10 ** abs(diff))
                        return val

                    # Apply correction dynamically row by row
                    df_consumption[col] = [
                        fix_scale_with_rolling(v, o) for v, o in zip(series, rolling_order)
                    ]

                    # Interpolations (remaining values)
                    ratio_fixed = series / rolling_mean
                    mask_still_bad = (ratio_fixed < 0.15) | (ratio_fixed > 6)
                    series[mask_still_bad] = np.nan

                    df = df.set_index('ds')
                    df[col] = df[col].interpolate(method='time')
                    df = df.reset_index()

                    # Smoothing
                    df[col] = series.rolling(11, min_periods=1, center=True).mean()
                    # self.plot_consumption_data(df)
            return df

        def clean_numeric_string( val):
            if pd.isna(val):
                return np.nan
            val = str(val)
            val = re.sub(r'[^\d\.\-eE]', '', val)
            if float(val) < 1:
                val = val.replace('.', '')
            try:
                return int(float(val))
            except InvalidOperation:
                return np.nan

        def normalize_consumption_data( df, time_columns):
            print('Printing values every 2000. Ends at 12000')
            for index, row in df.iterrows():
                if index % 2000 == 0:
                    print(row)
                values = row[time_columns]
                valid = values.dropna()
                if len(valid) == 0:
                    continue

                mean = valid.mean()
                max_val = valid.max()

                min_thresh = max_val / 5.5

                # Clean outliers
                cleaned = values.apply(lambda v: (
                    mean if (pd.isna(v) or v <= 0) else
                    v * pow(10, (round(log(max_val / v, 10)))) if (v < min_thresh) else
                    v
                ))

                df.loc[index, time_columns] = cleaned

        def extrapolate_features(df):
            df_consumption = df.rename(columns={'date': 'ds'})

            # Mapping of segments
            type_mapping = {
                'Small-Basso': 0,
                'Small-Alto': 1,
                'Medium-Basso': 2,
                'Medium-Alto': 3
            }

            df_consumption['segment'] = df_consumption['segment'].map(type_mapping)

            # Colonne con cui effettuare la normalizzazione
            colonne_consumo_orario = [f'val_consumo_{i}h' for i in range(1, 25)]
            colonne_posizione_consumi = ['lds_comune', 'segment', 'cluster_id']

            df_consumption = df_consumption.melt(
                id_vars=colonne_posizione_consumi + ['ds'],
                value_vars=colonne_consumo_orario,
                var_name='hour',
                value_name='consumption'
            )

            # Extract hour from column name like "val_consumo_1h"
            df_consumption['hour'] = (df_consumption['hour'].astype(str).str.extract(r'(\d+)').astype(int))
            # When hour is 24, go to the next day and change the hour to 0
            df_consumption.loc[df_consumption['hour'] == 24, 'ds'] = df_consumption.loc[df_consumption['hour'] == 24, 'ds'] + pd.DateOffset(days=1)
            df_consumption.loc[df_consumption['hour'] == 24, 'hour'] = 0

            print("ds type before conversion:", df_consumption['ds'].dtype)
            print("ds sample before conversion:", df_consumption['ds'].head())
            print("hour type before conversion:", df_consumption['hour'].dtype)
            print("hour sample before conversion:", df_consumption['hour'].head())

            # Convert date part to datetime and add hour as timedelta
            df_consumption['ds'] = pd.to_datetime(df_consumption['ds']) + pd.to_timedelta(df_consumption['hour'], unit='h')

            df_agg = (
                df_consumption.groupby(['ds', 'segment', 'lds_comune'], as_index=False)['consumption']
                .sum()
            )
            df_pivot = df_agg.pivot_table(
                index='ds',
                columns=['segment', 'lds_comune'],
                values='consumption'
            )
            df_pivot.rename(columns={'MILANO': 'Milano', 'NAPOLI': 'Napoli', 'ROMA': 'Roma'}, inplace=True)

            df_pivot.columns = [f"consumption_{seg}_{city}" for seg, city in df_pivot.columns]
            df_pivot = df_pivot.reset_index()

            interpolate_consumption_data(df_pivot)
            return df_pivot

        # Identify time columns (assuming they start from column 5 onward)
        time_columns = df.columns[4:-1]

        # Clean and convert to numeric
        for col in time_columns:
            df[col] = df[col].apply(clean_numeric_string)

        normalize_consumption_data(df, time_columns)
        df=extrapolate_features(df)
        print(df.head())
        df = df.rename(columns={'date': 'ds'})
        print(df.head())

        output_path = f'{final_name}'
        df.to_csv(output_path, index=False)
        print(f"Saved cleaned data to {output_path}")

        return df


    def get_weather_data(self,final_name=datasets_path['weather']):
        # Creates weather dataset 

        # Setup the Open-Meteo API client with cache and retry on error
        cache_session = requests_cache.CachedSession('.cache', expire_after=-1)
        retry_session = retry(cache_session, retries=5, backoff_factor=0.2)
        openmeteo = openmeteo_requests.Client(session=retry_session)

        # Make sure all required weather variables are listed here
        url = "https://archive-api.open-meteo.com/v1/archive"
        params = {
            "latitude": [40.8762, 45.4643, 41.8919],
            "longitude": [14.5195, 9.1895, 12.5113],
            "start_date": "2004-04-01",
            "end_date": "2025-10-06",
            "daily": ["temperature_2m_mean", "temperature_2m_max", "temperature_2m_min", "sunshine_duration", "rain_sum",
                    "wind_speed_10m_max", "shortwave_radiation_sum"],
            "hourly": ["temperature_2m", "rain", "wind_speed_10m", "cloud_cover_high"],
            "timezone": "auto",
        }
        responses = openmeteo.weather_api(url, params=params)

        # Process 3 locations
        for i, response in enumerate(responses):
            print(f"\nCoordinates: {response.Latitude()}°N {response.Longitude()}°E")
            print(f"Elevation: {response.Elevation()} m asl")
            print(f"Timezone: {response.Timezone()}{response.TimezoneAbbreviation()}")
            print(f"Timezone difference to GMT+0: {response.UtcOffsetSeconds()}s")

            # Process hourly data
            hourly = response.Hourly()
            hourly_temperature_2m = hourly.Variables(0).ValuesAsNumpy()
            hourly_rain = hourly.Variables(1).ValuesAsNumpy()
            hourly_wind_speed_10m = hourly.Variables(2).ValuesAsNumpy()
            hourly_cloud_cover_high = hourly.Variables(3).ValuesAsNumpy()

            hourly_data = {"date": pd.date_range(
                start=pd.to_datetime(hourly.Time(), unit="s", utc=True).tz_convert("Europe/Rome").tz_localize(None),
                end=pd.to_datetime(hourly.TimeEnd(), unit="s", utc=True).tz_convert("Europe/Rome").tz_localize(None),
                freq=pd.Timedelta(seconds=hourly.Interval()),
                inclusive="left"
            )}

            hourly_data["temperature_2m"] = hourly_temperature_2m
            hourly_data["rain"] = hourly_rain
            hourly_data["wind_speed_10m"] = hourly_wind_speed_10m
            hourly_data["cloud_cover_high"] = hourly_cloud_cover_high

            hourly_dataframe = pd.DataFrame(data=hourly_data)
            print("\nHourly data\n", hourly_dataframe)
            if i == 0:
                hourly_na = hourly_dataframe
            elif i == 1:
                hourly_mi = hourly_dataframe
            else:
                hourly_ro = hourly_dataframe

            # Process daily data
            daily = response.Daily()
            daily_temperature_2m_mean = daily.Variables(0).ValuesAsNumpy()
            daily_temperature_2m_max = daily.Variables(1).ValuesAsNumpy()
            daily_temperature_2m_min = daily.Variables(2).ValuesAsNumpy()
            daily_sunshine_duration = daily.Variables(3).ValuesAsNumpy()
            daily_rain_sum = daily.Variables(4).ValuesAsNumpy()
            daily_wind_speed_10m_max = daily.Variables(5).ValuesAsNumpy()
            daily_shortwave_radiation_sum = daily.Variables(6).ValuesAsNumpy()

            daily_data = {"date": pd.date_range(
                start=pd.to_datetime(daily.Time(), unit="s", utc=True).tz_convert("Europe/Rome").tz_localize(None),
                end=pd.to_datetime(daily.TimeEnd(), unit="s", utc=True).tz_convert("Europe/Rome").tz_localize(None),
                freq=pd.Timedelta(seconds=daily.Interval()),
                inclusive="left"
            )}

            daily_data["temperature_2m_mean"] = daily_temperature_2m_mean
            daily_data["temperature_2m_max"] = daily_temperature_2m_max
            daily_data["temperature_2m_min"] = daily_temperature_2m_min
            daily_data["sunshine_duration"] = daily_sunshine_duration
            daily_data["rain_sum"] = daily_rain_sum
            daily_data["wind_speed_10m_max"] = daily_wind_speed_10m_max
            daily_data["shortwave_radiation_sum"] = daily_shortwave_radiation_sum

            daily_dataframe = pd.DataFrame(data=daily_data)
            print("\nDaily data\n", daily_dataframe)
            if i == 0:
                daily_na = daily_dataframe
            elif i == 1:
                daily_mi = daily_dataframe
            else:
                daily_ro = daily_dataframe

        def merge_hourly_and_daily_weather_columns( hour_w, day_w, str):
            # Column 'day' for join
            hour_w['day'] = hour_w['date'].dt.date
            day_w['day'] = day_w['date'].dt.date

            # Merge on 'day'
            w_df = pd.merge(
                hour_w,
                day_w.drop(columns=['date']),
                on='day',
                how='left'
            )

            # Rename cells
            w_df.rename(columns={'temperature_2m': 't', 'wind_speed_10m_max': 'wind', 'cloud_cover_high': 'cloud_cover',
                                'temperature_2m_mean': 'tavg', 'temperature_2m_max': 'tmax', 'temperature_2m_min': 'tmin',
                                'sunshine_duration': 'sun_duration', 'wind_speed_10m_max': 'wind_max',
                                'shortwave_radiation_sum': 'short_rad_sum'}, inplace=True)
            w_df = w_df.add_suffix(f'_{str}')
            w_df.rename(columns={f'date_{str}': 'date'}, inplace=True)
            w_df = w_df.drop(columns=[f'day_{str}'])

            return w_df

        df_na = merge_hourly_and_daily_weather_columns(hourly_na, daily_na, 'Napoli')
        df_mi = merge_hourly_and_daily_weather_columns(hourly_mi, daily_mi, 'Milano')
        df_ro = merge_hourly_and_daily_weather_columns(hourly_ro, daily_ro, 'Roma')

        df_weather = df_na.merge(df_mi, how='left', on=['date'])
        df_weather = df_weather.merge(df_ro, how='left', on=['date'])
        df_weather = df_weather.rename(columns={'date': 'ds'})

        output_path = f'{final_name}'
        print(output_path)
        df_weather.to_csv(output_path, index=False)
        print(f"Saved cleaned data to {output_path}")
        return df_weather
    

    def get_price_data(self,final_name=datasets_path['price'],filepath=os.path.join(dataset_folder, filepath_gui_energy_prices)):
        # Detect all matching CSVs
        filepath=f"{filepath}*.csv"
        all_files = sorted(glob(filepath))
        print(filepath, '   ', all_files)

        if not all_files:
            raise FileNotFoundError(f"No files found for pattern: {pattern}")

        print(f"Found {len(all_files)} files:\n" + "\n".join(all_files))

        dfs = []
        for i, file in enumerate(all_files):
            df = pd.read_csv(file)

            # Parse 'ds' column 
            if 'MTU (UTC)' in df.columns:
                df["ds"] = df['MTU (UTC)'].str.split(" - ").str[0]
                df["ds"] = pd.to_datetime(df["ds"], format="%d/%m/%Y %H:%M:%S", utc=True)
            elif 'MTU (CET/CEST)' in df.columns:
                df["ds"] = df['MTU (CET/CEST)'].str.split(" - ").str[0]
                df["ds"] = (df["ds"]
                            .str.replace(r"\s*\(CE?ST\)", "", regex=True)
                            .pipe(pd.to_datetime, format="%d/%m/%Y %H:%M:%S", errors="coerce", utc=True))
            else:
                raise ValueError(f"Unknown time column in {file}")

            # Convert to Rome timezone (remove tzinfo)
            df["ds"] = df["ds"].dt.tz_convert("Europe/Rome").dt.tz_localize(None)

            # Handle last file (15-min intervals → hourly) 
            if i == len(all_files) - 1:
                print(f"Resampling last file to hourly: {os.path.basename(file)}")
                df = (df.set_index("ds")
                        .resample("1H")["Day-ahead Price (EUR/MWh)"]
                        .mean()
                        .reset_index())
                df["ds"] = df["ds"] + pd.DateOffset(hours=1)
            else:
                df = df[["ds", "Day-ahead Price (EUR/MWh)"]]

            dfs.append(df)

        #Concatenate all
        df = pd.concat(dfs, ignore_index=True)

        df.rename(columns={"Day-ahead Price (EUR/MWh)": 'y'}, inplace=True)
        df["y"] = pd.to_numeric(df["y"], errors="coerce")
        df = df[['ds', 'y']].dropna()

        # Save output
        output_path = f'{final_name}'
        df.to_csv(output_path, index=False)
        print(f"\n Saved merged data to {output_path} ({len(df)} rows)")

        return df


    def ensure_datasets_present(self,base_path="datasets_folder"):
        """
        Ensure that required CSV datasets exist. If missing, automatically
        run the external scripts that generate them.

        Args:
            base_path: path where datasets are expected or saved
        """
        os.makedirs(base_path, exist_ok=True)

        weather_csv = datasets_path['weather']
        # Weather dataset
        if not os.path.exists(weather_csv):
            print("[INFO] Weather dataset missing, generating it...")
            try:
                importlib.import_module(weather_csv)
            except ModuleNotFoundError:
                print(f"{weather_csv}  not found — creating weather dataset...")
                self.df_weather= self.get_weather_data(weather_csv)


        # Price dataset
        price_csv = datasets_path['price']
        if not os.path.exists(price_csv):
            print("[INFO] Price dataset missing, generating it...")
            try:
                importlib.import_module(price_csv)
            except ModuleNotFoundError:
                print(f"{price_csv} not found — creating price dataset...")  
                path = os.path.join(base_path, filepath_gui_energy_prices)
                self.df_price= self.get_price_data(price_csv,filepath=path)
                

        # Consumption dataset 
        consumption_csv = datasets_path['consumption']
        if not os.path.exists(consumption_csv):
            print("[INFO] Consumption dataset missing, generating it...")
            try:
                importlib.import_module(consumption_csv)
            except ModuleNotFoundError:
                print(f"{consumption_csv}  not found — creating consumption dataset...")
                path = os.path.join(base_path, filepath_innothon_consumption_dataset)
                self.df_consumption= self.get_energy_consumption_data(consumption_csv,filepath=path)


class DataLoaderClass:
    def __init__(self, datasets_path):
        self.price_data_path     = datasets_path['price']
        self.consumption_data_path    = datasets_path['consumption']
        self.weather_data_path = datasets_path['weather']
        self.create_datasets   = CreateDatasets()
        print("Checking datasets...")
        self.create_datasets.ensure_datasets_present(dataset_folder)
        self.df_price= self.create_datasets.df_price
        self.df_weather= self.create_datasets.df_weather
        self.df_consumption= self.create_datasets.df_consumption

    def load_price_data(self):
        """load price data"""
        if self.df_price is None:
            self.df_price     = pd.read_csv(self.price_data_path, parse_dates=['ds'])
        return self.df_price


    def load_weather_data(self):
        """load weather data"""
        if self.df_weather is None:
            self.df_weather    = pd.read_csv(self.weather_data_path, parse_dates=['ds'])
        return self.df_weather
    
       
    def load_consumption_data(self):
        """load consumption data"""
        if self.df_consumption is None:
            self.df_consumption   = pd.read_csv(self.consumption_data_path, parse_dates=['ds'])
        return self.df_consumption


class DataIntegrator:
    def __init__(self, cities=['Milano', 'Roma', 'Napoli']):
        self.cities = cities


    def integrate_consumption_data(self, df_price, df_consumption):
        """Get only 2024 for constumptions"""
        if df_consumption is None:
            # print("Nessun dato di consumo disponibile")
            return df_price

        # Get only 2024 for constumptions
        df_consumption_2024 = df_consumption[df_consumption['ds'].dt.year == 2024].copy()

        # Merge price with consumption
        df_merged = pd.merge(df_price,df_consumption_2024,on='ds',how='right')

        # Per periodi pre-2024, i consumi saranno NaN - possiamo interpolare o usare medie stagionali
        # print(f"Dati consumo integrati. {len(df_consumption_2024)} record del 2024")

        return df_merged


    def integrate_weather_data(self, df, df_weather):
        if df_weather is None:
            # print("Nessun dato meteo disponibile")
            return df

        # Unisci dati meteo
        df_merged = pd.merge(df, df_weather, on='ds', how='left')

        # Verifica colonne meteo presenti
        weather_cols = [col for col in df_weather.columns if col !=[ 'ds']]
        # print(f"Colonne meteo integrate: {weather_cols}")

        return df_merged


class FeatureEngineer:
    def __init__(self, temp_baseline=18.0):
        self.temp_baseline = temp_baseline
        self.scalers = {}


    def add_weather_features(self, df, cities):
        """Weather features for each city"""
        df = df.copy()

        for city in cities:
            # Cooling Degree Days
            df[f'tavg_{city}_lag_24'] = df[f'tavg_{city}'].shift(24)
            df[f'CDD_{city}'] = np.maximum(0, df[f'tavg_{city}'] - self.temp_baseline)

            # Temperature spikes vs mean
            df[f'temp_{city}_spike_vs_mean'] = df[f't_{city}'] - df[f'tavg_{city}']

            # Altre feature temperatura
            df[f'tmax_{city}_lag_24'] = df[f'tmax_{city}'].shift(24) if f'tmax_{city}' in df.columns else df[f'tavg_{city}'].shift(24)
            df[f'tmax_{city}_lag_48'] = df[f'tmax_{city}'].shift(48) if f'tmax_{city}' in df.columns else df[f'tavg_{city}'].shift(48)
            df[f'tmax_{city}_lag_168'] = df[f'tmax_{city}'].shift(168) if f'tmax_{city}' in df.columns else df[f'tavg_{city}'].shift(168)
            df[f'tmin_{city}_lag_24'] = df[f'tmin_{city}'].shift(24) if f'tmin_{city}' in df.columns else df[f'tavg_{city}'].shift(24)
            df[f'tmin_{city}_lag_48'] = df[f'tmin_{city}'].shift(48) if f'tmin_{city}' in df.columns else df[f'tavg_{city}'].shift(48)
            df[f'tmin_{city}_lag_168'] = df[f'tmin_{city}'].shift(168) if f'tmin_{city}' in df.columns else df[f'tavg_{city}'].shift(168)

            # Feature ore di sole (se disponibili)
            if f'sunshine_{city}' in df.columns:
                df[f'sunshine_{city}_lag_24'] = df[f'sunshine_{city}'].shift(24)

        return df


    def add_consumption_features(self, df, cities):
        """Consumption features for each city-segment"""
        df = df.copy()
        segments=range(4)

        for city in cities:
             for seg in segments:
                consumption_col = f'consumption_{seg}_{city}'
                if consumption_col not in df.columns:
                    continue

                # Rolling statistics per il carico
                df[f'consumption_{seg}_{city}_roll_mean_24'] = df[consumption_col].rolling(24, min_periods=1).mean().shift(1)
                df[f'consumption_{seg}_{city}_roll_std_24'] = df[consumption_col].rolling(24, min_periods=1).std().shift(1)
                df[f'consumption_{seg}_{city}_roll_max_24'] = df[consumption_col].rolling(24, min_periods=1).max().shift(1)
                # df[f'consumption_{seg}_{city}_roll_mean_336'] = df[consumption_col].rolling(336, min_periods=1).mean().shift(1)  # 2 settimane
                df[f'consumption_{seg}_{city}_roll_std_168'] = df[consumption_col].rolling(168, min_periods=1).std().shift(1)    # 1 settimana

                # Spike detection
                df[f'consumption_{seg}_{city}_spike_vs_mean'] = df[consumption_col] - df[f'consumption_{seg}_{city}_roll_mean_24']

                # Normalizza gli spike
                rolling_std = df[f'consumption_{seg}_{city}_roll_std_24'].replace(0, 1)  # Evita divisione per zero
                df[f'consumption_{seg}_{city}_spike_norm'] = df[f'consumption_{seg}_{city}_spike_vs_mean'] / rolling_std

        return df


    def add_price_features(self, df):
        """Price features"""
        df = df.copy()


        # Lag statistics
        for lag in [1,2,3,4,5,6,7,8,9,10,12,16,24,36,48,72,168,336,672]:#,336,672
            df[f'y_lag_{lag}']  = df['y'].shift(lag)

        # # Trend features
        for lag in [1,2,4,24,48,168,336,672]:
                df[f'y_minus_{lag}']  = df[f'y']-df[f'y_lag_{lag}']

        # #  More Trend features
        # for lag1 in [1,2,6,24,168,336]:
        #     for lag2 in [2,4,24,48,168,336,672]:
        #         if lag1==lag2:
        #             continue
        #         df[f'y_lag_{lag1}_minus_{lag2}']  = df[f'y_lag_{lag1}']-df[f'y_lag_{lag2}']

        # Volatility regimes
        short_vol = df['y'].rolling(24).std()
        long_vol = df['y'].rolling(168).std()
        df['volatility_ratio'] = short_vol / long_vol.replace(0, 1)
        df['high_volatility'] = (df['volatility_ratio'] > 1.5).astype(int)

        # Price level regimes
        for t in [2,6,24,48,168,336]:
            df['price_quantile_{t}_25'] = df['y'].rolling(t).quantile(0.25)
            df['price_quantile_{t}_75'] = df['y'].rolling(t).quantile(0.75)
            df['is_high_price_{t}'] = (df['y'] > df['price_quantile_{t}_75']).astype(int)
            df['is_low_price_{t}']  = (df['y'] < df['price_quantile_{t}_25']).astype(int)

        # Rolling statistics
        for t in [2,3,4,6,24,48,168,336]: #don't go over 168, there are no values because you took 24*7=168, with shift 1 mean it won't be taken in Nhits

            df[f'y_roll_min_{t}']  = df['y'].rolling(t, min_periods=1).min()
            df[f'y_roll_max_{t}']  = df['y'].rolling(t, min_periods=1).max()
            df[f'y_roll_mean_{t}'] = df['y'].rolling(t, min_periods=1).mean()
            df[f'y_roll_std_{t}']  = df['y'].rolling(t, min_periods=1).std()
            # df[f'y_roll_mean_minus_std_{t}'] = df[f'y_roll_mean_{t}'] - df[f'y_roll_std_{t}']
            df[f'y_roll_mean_plus_std_{t}']  = df[f'y_roll_mean_{t}'] + df[f'y_roll_std_{t}']
            # df[f'y_roll_max_minus_min_norm{t}']  = (df[f'y_roll_max_{t}']  - df[f'y_roll_min_{t}']/df[f'y_roll_mean_{t}'])
            df[f'y_roll_max_minus_mean{t}']  = df[f'y_roll_max_{t}']  - df[f'y_roll_mean_{t}']
            df[f'y_roll_max_minus_min{t}']   = df[f'y_roll_max_{t}']  - df[f'y_roll_min_{t}']
            # df[f'y_roll_mean_minus_min{t}']  = df[f'y_roll_mean_{t}'] - df[f'y_roll_min_{t}']

        ## lagged normalized on day values
        for lag in [0,1,2,3,4,5,6,7,8,9,10,12,16,24]:#,336,672
            df[f'y_lag_{lag}_norm_24']  = df['y'].shift(lag)/df[f'y_roll_max_minus_min24'].replace(0, 1)

        #Rolling Windows shifter
        for t in [2,24,168,336]:
            for sh in [1,4,6,24,48,72,168]:
                df[f'y_roll_min_{t}_shift{sh}']   = df['y'].rolling(t, min_periods=1).min().shift(sh)
                df[f'y_roll_max_{t}_shift{sh}']   = df['y'].rolling(t, min_periods=1).max().shift(sh)
                df[f'y_roll_mean_{t}_shift{sh}']   = df['y'].rolling(t, min_periods=1).mean().shift(sh)

        # Rolling Windows comparisons
        for t1 in [2,4,6,24,48]: #don't go over 168, there are no values because you took 24*7=168, with shift 1 mean it won't be taken in Nhits
            for t2 in [4,24,48,168]:
                if t1<t2:
                    continue
                df[f'y_roll_max_{t1}_minus_max_{t2}']   = df[f'y_roll_max_{t1}']  - df[f'y_roll_max_{t2}']
                df[f'y_roll_mean_{t1}_minus_mean_{t2}']   = df[f'y_roll_mean_{t1}']  - df[f'y_roll_mean_{t2}']
                # df[f'y_roll_min_{t1}_minus_min_{t2}']   = df[f'y_roll_min_{t1}']  - df[f'y_roll_min_{t2}']

        # Spike detection
        for t in [2,3,4,6,24,48,168,336]:
            df[f'y_spike_vs_mean{t}'] = df['y'] - df[f'y_roll_mean_{t}']
            df[f'y_spike_vs_max{t}'] = df['y'] - df[f'y_roll_max_{t}']
            df[f'y_spike_vs_min{t}'] = df['y'] - df[f'y_roll_min_{t}']

            # Normalizza gli spike
            rolling_std = df[f'y_roll_std_{t}'].replace(0, 1)  # Evita divisione per zero
            df[f'y_spike_norm{t}_1']  = df[f'y_spike_vs_mean{t}'] / rolling_std
            df[f'y_spike_norm{t}2']  = df[f'y_spike_vs_max{t}'] / rolling_std
            df[f'y_spike_norm{t}3']  = df[f'y_spike_vs_min{t}'] / rolling_std


        return df


    def add_weather_cross_features(self, df, cities):
        """Aggiunge feature incrociate tra meteo e carico"""
        df = df.copy()

        for city in cities:
            if f'consumption_{city}' in df.columns:
                # Interazione tra CDD e price
                df[f'CDD_{city}_x_y'] = df[f'CDD_{city}'] * df[f'y']
                # Interazione tra temperatura e price
                df[f'temp_{city}_x_y'] = df[f'tavg_{city}'] * df[f'y']
                # Interazione tra CDD e hour
                df[f'CDD_{city}_x_hour'] = df[f'CDD_{city}'] * (df['hour'] / 24.0)


        return df


    def add_temporal_features(self, df):
        """Aggiunge feature temporali"""
        df = df.copy()
        df['hour'] = df['ds'].dt.hour
        df['distance_to_peak'] = abs(df['hour']-14)
        df['peak_score'] = 1 / (1 + df['distance_to_peak'])  # or other scaling
        df['day_of_week'] = df['ds'].dt.dayofweek
        df['day_of_year'] = df['ds'].dt.dayofyear
        df['month'] = df['ds'].dt.month
        df['is_weekend'] = df['day_of_week'].isin([5, 6]).astype(int)
        df['season'] = (df['month'] % 12 + 3) // 3  # 1=Winter, 2=Spring, etc.

        df['is_monday'] = (df['day_of_week'] == 0).astype(int)
        df['is_friday'] = (df['day_of_week'] == 4).astype(int)

        # **Time of day segments**
        df['is_night'] = ((df['hour'] >= 0) & (df['hour'] <= 5)).astype(int)
        df['is_morning_peak'] = ((df['hour'] >= 6) & (df['hour'] <= 9)).astype(int)
        df['is_day'] = ((df['hour'] >= 10) & (df['hour'] <= 17)).astype(int)
        df['is_evening_peak'] = ((df['hour'] >= 18) & (df['hour'] <= 21)).astype(int)
        df['is_late_evening'] = ((df['hour'] >= 22) & (df['hour'] <= 23)).astype(int)

        # **Seasonal features**
        df['is_winter'] = df['season']==1
        df['is_spring'] = df['season']==2
        df['is_summer'] = df['season']==3
        df['is_fall'] = df['season']==4


        holidays=['2024-01-01','2024-01-06','2024-04-01','2024-04-25','2024-05-01','2024-06-02','2024-08-15','2024-11-01','2024-12-08','2024-12-25','2024-12-26','2024-12-31']
        df['is_holiday']=df['ds'].apply(lambda x: 1 if x in holidays  else 0)

        # Feature cicliche
        df['hour_sin'] = np.sin(2 * np.pi * df['hour'] / 24)
        df['hour_cos'] = np.cos(2 * np.pi * df['hour'] / 24)
        df['day_of_week_sin'] = np.sin(2 * np.pi * df['day_of_week'] / 7)
        df['day_of_week_cos'] = np.cos(2 * np.pi * df['day_of_week'] / 7)
        df['day_of_year_sin'] = np.sin(2 * np.pi * df['day_of_year'] / 365)
        df['day_of_year_cos'] = np.cos(2 * np.pi * df['day_of_year'] / 365)


        # **Same hour from previous days** - very important!
        for days_back in [1, 2, 3, 7, 14, 28]:
            df[f'same_hour_{days_back}d_ago'] = df['y'].shift(24 * days_back)


        # **Weekly pattern features**
        df['same_day_last_week'] = df['y'].shift(24 * 7)
        df['week_over_week_change'] = df['y'] - df['y'].shift(24 * 7)

        return df


    def add_temporal_cross_features(self, df):
        """Aggiunge feature incrociate tra meteo e carico"""
        df = df.copy()

        df['hour_weekend_interaction'] = df['hour'] * df['is_weekend']
        df['hour_month_interaction'] = df['hour'] * df['month']

        # **Volatility * Time interactions**
        df['volatility_morning_peak'] = df['volatility_ratio'] * df['is_morning_peak']
        df['volatility_evening_peak'] = df['volatility_ratio'] * df['is_evening_peak']

        # **Previous day * Current hour**
        df['prev_day_mean_hour_interaction'] = df['y_roll_mean_24'] * df['hour']

        return df


    def create_all_features(self, df, cities=['Milano', 'Roma', 'Napoli']):
        """Crea tutte le feature avanzate"""
        print("Creazione feature avanzate...")

        # Price features
        if add_price_features_bool :
            df = self.add_price_features(df)

        # Weather features
        if merge_weather_data_bool and add_weather_features_bool:
            df = self.add_weather_features(df, cities)

        # Load features
        if merge_consumptions_data_bool and add_consumption_features_bool:
            df = self.add_consumption_features(df, cities)


        # Temporal features
        if add_temporal_features_bool:
            df = self.add_temporal_features(df)


        # Cross features
        if add_cross_features_bool:
            df = self.add_temporal_cross_features(df)

        if merge_weather_data_bool and add_weather_features_bool and add_temporal_features_bool:
            df = self.add_weather_cross_features(df, cities)

        # Riempimento NaN
        df = df.fillna(method='bfill').fillna(method='ffill')

        print(f"Feature created: {len([col for col in df.columns if col not in ['ds', 'y']])}")
        # print(f"{[col for col in df.columns if col not in [ 'ds', 'y']]}")
        return df


class EarlyStopping:
    def __init__(self, patience=10, verbose=False, delta=0):
        self.patience = patience
        self.verbose = verbose
        self.delta = delta
        self.best_score = None
        self.early_stop = False
        self.val_loss_min = np.inf
        self.counter = 0

    def __call__(self, val_loss):
        score = val_loss
        if self.best_score is None:
            self.best_score = score
        elif score > self.best_score + self.delta:
            self.counter += 1
            if self.verbose:
                print(f'EarlyStopping counter: {self.counter} out of {self.patience}')
            if self.counter >= self.patience:
                self.early_stop = True
        else:
            self.best_score = score
            self.counter = 0


class PyTorchForecastingModel:
    """Base class for PyTorch forecasting models, handling training, prediction, saving, and loading."""
    def __init__(self, params, scaler_x=None, scaler_y=None):
        self.params = params
        self.scaler_x = scaler_x
        self.scaler_y = scaler_y
        self.model = None
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        print(f"Using device: {self.device}")

    def hybrid_peak_loss(self, pred, target, alpha=0.8, q=0.9):
        base = torch.mean((pred - target) ** 2)
        threshold = torch.quantile(target, q)
        peak_mask = (target > threshold).float()
        peak_loss = torch.mean(peak_mask * (pred - target) ** 2)
        return alpha * base + (1 - alpha) * peak_loss

    def train(self, X_train, y_train, X_val=None, y_val=None):
        # Convert data to PyTorch tensors
        X_train_tensor = torch.from_numpy(X_train).float().to(self.device)
        y_train_tensor = torch.from_numpy(y_train).float().to(self.device)

        train_dataset = TensorDataset(X_train_tensor, y_train_tensor)
        train_loader = DataLoader(train_dataset, batch_size=self.params['batch_size'], shuffle=True)

        self.model.to(self.device)
        optimizer = optim.Adam(self.model.parameters(), lr=self.params['learning_rate'])
        criterion = lambda pred, target: self.hybrid_peak_loss(pred, target, alpha=0.8, q=0.9)
        early_stopping = EarlyStopping(patience=15, verbose=True)

        for epoch in range(self.params['epochs']):
            self.model.train()
            train_loss = 0
            for X_batch, y_batch in train_loader:
                optimizer.zero_grad()
                outputs = self.model(X_batch)
                loss = criterion(outputs, y_batch)
                loss.backward()
                optimizer.step()
                train_loss += loss.item()

            train_loss /= len(train_loader)

            # Validation step
            if X_val is not None and y_val is not None:
                self.model.eval()
                with torch.no_grad():
                    X_val_tensor = torch.from_numpy(X_val).float().to(self.device)
                    y_val_tensor = torch.from_numpy(y_val).float().to(self.device)
                    val_outputs = self.model(X_val_tensor)
                    val_loss = criterion(val_outputs, y_val_tensor).item()
                print(f"Epoch {epoch+1}/{self.params['epochs']}, Train Loss: {train_loss:.4f}, Val Loss: {val_loss:.4f}")
                early_stopping(val_loss)
                if early_stopping.early_stop:
                    print("Early stopping triggered")
                    break
            else:
                print(f"Epoch {epoch+1}/{self.params['epochs']}, Train Loss: {train_loss:.4f}")

    def predict(self, X):
        self.model.eval()
        with torch.no_grad():
            X_tensor = torch.from_numpy(X).float().to(self.device)
            predictions = self.model(X_tensor)
        return predictions.cpu().numpy()

    def save(self, filepath_base):
        torch.save(self.model.state_dict(), f"{filepath_base}.pth")
        if self.scaler_x:
            with open(f"{filepath_base}_scaler_x.pkl", 'wb') as f:
                pickle.dump(self.scaler_x, f)
        if self.scaler_y:
            with open(f"{filepath_base}_scaler_y.pkl", 'wb') as f:
                pickle.dump(self.scaler_y, f)
        print(f"Model and scalers saved to {filepath_base}.*")

    def load(self, filepath_base):
        # The model architecture must be defined before loading the state_dict
        if self.model is None:
            raise ValueError("Initialize the model architecture before loading weights.")
        self.model.load_state_dict(torch.load(f"{filepath_base}.pth", map_location="cpu", weights_only=True))
        self.model.to(self.device)
        try:
            with open(f"{filepath_base}_scaler_x.pkl", 'rb') as f: self.scaler_x = pickle.load(f)
        except FileNotFoundError: self.scaler_x = None
        try:
            with open(f"{filepath_base}_scaler_y.pkl", 'rb') as f: self.scaler_y = pickle.load(f)
        except FileNotFoundError: self.scaler_y = None


class NBEATS(PyTorchForecastingModel):
    def __init__(self, params, scaler_x=None, scaler_y=None):
        super().__init__(params, scaler_x, scaler_y)
        self.model = NBEATS_Net(params)


class NBEATS_Block(nn.Module):
    def __init__(self, params, stack_type):
        super().__init__()
        self.params = params
        self.stack_type = stack_type
        self.n_in = params['n_in']
        self.n_out = params['n_out']
        self.n_features = params['n_features']

        layers = [nn.Linear(self.n_in * self.n_features, params['layer_width']), nn.ReLU()]
        for _ in range(params['n_layers'] - 1):
            layers.extend([nn.Linear(params['layer_width'], params['layer_width']), nn.ReLU()])
        self.mlp = nn.Sequential(*layers)

        if stack_type == 'generic':
            self.theta_b = nn.Linear(params['layer_width'], self.n_in * self.n_features)
            self.theta_f = nn.Linear(params['layer_width'], self.n_out)
        elif stack_type == 'trend':
            p = params['theta_dim']
            self.theta_b = nn.Linear(params['layer_width'], p)
            self.theta_f = nn.Linear(params['layer_width'], p)
            t_back = torch.arange(self.n_in, dtype=torch.float32) / self.n_in
            self.back_poly = torch.stack([t_back ** i for i in range(p)], 1)
            t_fore = torch.arange(self.n_out, dtype=torch.float32) / self.n_out
            self.fore_poly = torch.stack([t_fore ** i for i in range(p)], 1)
        elif stack_type == 'seasonality':
            H = params['n_harmonics']
            self.theta_b = nn.Linear(params['layer_width'], 2 * H)
            self.theta_f = nn.Linear(params['layer_width'], 2 * H)
            t = torch.arange(params['seasonality_period'], dtype=torch.float32)
            harmonics = torch.cat([
                torch.cos(2 * np.pi * i * t / params['seasonality_period']) for i in range(1, H + 1)] + [
                torch.sin(2 * np.pi * i * t / params['seasonality_period']) for i in range(1, H + 1)]
            ).reshape(2*H, -1)
            self.back_harmonics = harmonics[:, :self.n_in].T
            self.fore_harmonics = harmonics[:, :self.n_out].T

    def forward(self, x):
        x_flat = x.view(x.size(0), -1)
        hidden = self.mlp(x_flat)

        if self.stack_type == 'generic':
            theta_b = self.theta_b(hidden)
            theta_f = self.theta_f(hidden)
            backcast = theta_b.view(-1, self.n_in, self.n_features)
            forecast = theta_f
        elif self.stack_type == 'trend':
            theta_b = self.theta_b(hidden)
            theta_f = self.theta_f(hidden)
            back_poly = self.back_poly.to(x.device)
            fore_poly = self.fore_poly.to(x.device)
            backcast_trend = torch.einsum('bi,ji->bj', theta_b, back_poly)
            forecast_trend = torch.einsum('bi,ji->bj', theta_f, fore_poly)
            backcast = backcast_trend.unsqueeze(-1).repeat(1, 1, self.n_features)
            forecast = forecast_trend
        elif self.stack_type == 'seasonality':
            theta_b = self.theta_b(hidden)
            theta_f = self.theta_f(hidden)
            back_harmonics = self.back_harmonics.to(x.device)
            fore_harmonics = self.fore_harmonics.to(x.device)
            backcast_seasonal = torch.einsum('bi,ji->bj', theta_b, back_harmonics)
            forecast_seasonal = torch.einsum('bi,ji->bj', theta_f, fore_harmonics)
            backcast = backcast_seasonal.unsqueeze(-1).repeat(1, 1, self.n_features)
            forecast = forecast_seasonal
        return backcast, forecast


class NBEATS_Net(nn.Module):
    def __init__(self, params):
        super().__init__()
        self.stacks = nn.ModuleList([
            NBEATS_Block(params, stack_type) for stack_type in params['stack_types'] for _ in range(params['n_blocks'])
        ])

    def forward(self, x):
        backcast_residual = x
        total_forecast = 0
        for block in self.stacks:
            backcast, forecast = block(backcast_residual)
            backcast_residual = backcast_residual - backcast
            total_forecast = total_forecast + forecast
        return total_forecast


class NHITS(PyTorchForecastingModel):
    def __init__(self, params, scaler_x=None, scaler_y=None):
        super().__init__(params, scaler_x, scaler_y)
        self.model = NHITS_Net(params)


class NHITS_Net(nn.Module):
    def __init__(self, params):
        super().__init__()
        self.params = params
        self.stacks = nn.ModuleList()
        num_stacks = len(params['n_blocks'])
        for i in range(num_stacks):
            for _ in range(params['n_blocks'][i]):
                self.stacks.append(NHITS_Block(params, stack_num=i))

    def forward(self, x):
        backcast_residual = x
        total_forecast = 0
        for block in self.stacks:
            backcast, forecast = block(backcast_residual)
            backcast_residual = backcast_residual - backcast
            total_forecast = total_forecast + forecast
        return total_forecast


class NHITS_Block(nn.Module):
    def __init__(self, params, stack_num):
        super().__init__()
        self.n_in = params['n_in']
        self.n_out = params['n_out']
        self.n_features = params.get('n_features', 1)

        pool_size = params['pool_kernel_sizes'][stack_num]
        #try with MaxPool1d
        # self.pool = nn.AvgPool1d(kernel_size=pool_size, stride=pool_size) if pool_size > 1 else None
        self.pool = nn.MaxPool1d(kernel_size=pool_size, stride=pool_size) if pool_size > 1 else None

        pooled_len = (self.n_in * self.n_features) // pool_size

        mlp_layers = [nn.Linear(pooled_len, params['mlp_units'][0]), nn.ReLU()]
        for i in range(len(params['mlp_units']) - 1):
             mlp_layers.extend([nn.Linear(params['mlp_units'][i], params['mlp_units'][i+1]), nn.ReLU()])
        self.mlp = nn.Sequential(*mlp_layers)

        n_downsample = params['n_freq_downsample'][stack_num]
        self.theta_b = nn.Linear(params['mlp_units'][-1], self.n_in // n_downsample)
        self.theta_f = nn.Linear(params['mlp_units'][-1], self.n_out // n_downsample)

        self.backcast_layer = nn.Linear(self.n_in // n_downsample, self.n_in * self.n_features)
        self.forecast_layer = nn.Linear(self.n_out // n_downsample, self.n_out)

    def forward(self, x):
        x_flat = x.reshape(x.size(0), 1, -1)

        if self.pool:
            pooled = self.pool(x_flat).squeeze(1)
        else:
            pooled = x_flat.squeeze(1)

        mlp_out = self.mlp(pooled)

        theta_b = self.theta_b(mlp_out)
        theta_f = self.theta_f(mlp_out)

        backcast = self.backcast_layer(theta_b).view(-1, self.n_in, self.n_features)
        forecast = self.forecast_layer(theta_f)

        return backcast, forecast


class PriceForecaster:
    def __init__(self, datasets_path, cities=['Milano', 'Roma', 'Napoli']):
        self.cities = cities
        self.scaler_y = None
        self.scaler_x = None
        self.data_loader = DataLoaderClass(datasets_path)
        self.feature_engineer = FeatureEngineer()
        self.data_integrator = DataIntegrator(cities)
        self.xgb_model = None
        self.nhits_model = None
        self.nbeats_model = None
        add_interval_methods_to_forecaster()



    def load_and_prepare_data(self):
        """Load and prepare all datasets"""
        print("Loading price data...")
        df_price = self.data_loader.load_price_data()

        df_weather = None
        if merge_weather_data_bool:
            print("Loading weather data...")
            df_weather = self.data_loader.load_weather_data()

        df_consumption = None
        if merge_consumptions_data_bool:
            print("Loading consumption data...")
            df_consumption = self.data_loader.load_consumption_data()
            
        # Integrate all data
        print("Integrating data...")
        df_merged = self.data_integrator.integrate_consumption_data(df_price, df_consumption)
        df_merged = self.data_integrator.integrate_weather_data(df_merged, df_weather)

        return df_merged


    def prepare_features(self, df):
        """Prepare features for modeling"""
        print("Engineering features...")
        df_processed = self.feature_engineer.create_all_features(
            df, self.cities
        )

        # Separate target and features
        feature_columns = [col for col in df_processed.columns
                         if col not in ['ds', 'y']]

        return df_processed, feature_columns


    def normalize_data(self, df, feature_columns, fit_scaler=False):
        """Normalize the data"""
        if fit_scaler:
            self.scaler_y = StandardScaler()
            self.scaler_x = StandardScaler()

            # Normalize target
            y_values = df['y'].values.reshape(-1, 1)
            df['y_normalized'] = self.scaler_y.fit_transform(y_values)

            # Normalize features
            if len(feature_columns) > 0:
                X_values = df[feature_columns].values
                df[feature_columns] = self.scaler_x.fit_transform(X_values)
        else:
            # Use existing scalers
            y_values = df['y'].values.reshape(-1, 1)
            df['y_normalized'] = self.scaler_y.transform(y_values)

            if len(feature_columns) > 0 and self.scaler_x is not None:
                X_values = df[feature_columns].values
                df[feature_columns] = self.scaler_x.transform(X_values)

        return df


    def create_sequences_xgboost(self,df,  feature_columns, skip_size=0, train_size=0.85,val_size=0.1,test_size=0.1,horizon=xgb_params['num_target']):

        X = df[feature_columns]

        # Create multiple target columns for each horizon
        target_columns = []
        for h in range(1, horizon + 1):
            target_col = f'y_h{h}'
            df[target_col] = df['y_normalized'].shift(-h)
            target_columns.append(target_col)

        # Remove rows with NaN targets (last 24 hours of all the dataset, because there are no y_test values to evaluate with)
        start_train=int(len(X)*skip_size)
        X = X.iloc[start_train:-horizon]
        y = df[target_columns].dropna()
        y = y.iloc[start_train:]

        # Split data
        train_end = int(len(X) *train_size)
        val_end = int(len(X) * val_size)
        test_end = int(len(X) * test_size)

        X_train, X_val, X_test = X.iloc[:train_end], X.iloc[train_end:train_end+val_end], X.iloc[train_end+val_end:train_end+val_end+test_end]
        y_train, y_val, y_test = y.iloc[:train_end], y.iloc[train_end:train_end+val_end], y.iloc[train_end+val_end:train_end+val_end+test_end]
        print('X_train: ',X_train.shape,'\tX_val: ',X_val.shape,'\tX_test: ',X_test.shape)
        print('y_train: ',y_train.shape,'\ty_val: ',y_val.shape,'\ty_test: ',y_test.shape)
        return X_train, X_val, X_test, y_train, y_val, y_test


    def prepare_sequences_time_based(self, df, feature_columns, n_in=24*7, n_out=24, step=168, skip_size=0.1, train_ratio=0.84, val_ratio=0.1):
        """Prepare data for NHITS model with exogenous features"""
        all_features = ['y_normalized'] + feature_columns
        df_seq=df.iloc[int(len(df)*skip_size):].copy()
        df_seq = df_seq[all_features]
        # df_seq = df_seq.sort_values('ds').reset_index(drop=True)

        arr = df_seq.to_numpy()
        total_sequences = (len(arr) - n_in - n_out + 1)
        if total_sequences <= 0:
            raise ValueError("Not enough data to create a single sequence. Reduce n_in or n_out.")

        train_end = int(total_sequences * train_ratio)
        val_end = train_end + int(total_sequences * val_ratio)
        test_end=  train_end +val_end + int(total_sequences * (test_size))

        X_tr, y_tr, X_v, y_v, X_te, y_te = [], [], [], [], [], []

        for i in range(0, len(arr) - n_in - n_out + 1, step):
            x = arr[i : i + n_in, :]
            y = arr[i + n_in : i + n_in + n_out, 0]  # Use 0 or -1 based on your data

            if i <= train_end:
                X_tr.append(x); y_tr.append(y)
            elif i <= val_end:
                X_v.append(x); y_v.append(y)
            elif i <= test_end:
                X_te.append(x); y_te.append(y)

        # Convert to arrays and ensure float64
        X_tr, y_tr = np.array(X_tr).astype('float32'), np.array(y_tr).astype('float32')
        X_v, y_v = np.array(X_v).astype('float32'), np.array(y_v).astype('float32')
        X_te, y_te = np.array(X_te).astype('float32'), np.array(y_te).astype('float32')

        print(f"Sequences - Train: {X_tr.shape}, Val: {X_v.shape}, Test: {X_te.shape}")
        print(f"Sequences - Train: {y_tr.shape}, Val: {y_v.shape}, Test: {y_te.shape}")
        return X_tr, y_tr, X_v, y_v, X_te, y_te


    def plot_losses(self, history):
        # Plot training history for NHITS
        plt.figure(figsize=(12, 4))
        plt.subplot(1, 2, 1)
        plt.plot(history.history['loss'], label='Training Loss')
        plt.plot(history.history['val_loss'], label='Validation Loss')
        plt.title('Model Loss')
        plt.xlabel('Epoch')
        plt.ylabel('Loss')
        plt.legend()

        plt.subplot(1, 2, 2)
        plt.plot(history.history['mae'], label='Training MAE')
        plt.plot(history.history['val_mae'], label='Validation MAE')
        plt.title('Model MAE')
        plt.xlabel('Epoch')
        plt.ylabel('MAE')
        plt.legend()

        plt.tight_layout()
        plt.show()


    def train_nbeats(self, X_train, y_train, X_val=None, y_val=None, params=None):

        if params is None:

            params = {
                'n_in': 24*7,
                'n_out': 24,
                'step' :168,
                'seasonality_period': 168,
                'n_blocks': 3,
                'n_layers': 4,
                'layer_width': 256,
                'theta_dim': 16,
                'dropout_rate': 0.2,
                'learning_rate': 0.001,
                'stack_types': ['trend', 'seasonality', 'trend', 'generic'],
                'n_harmonics': 4

            }
        train_losses = []
        val_losses = []
        self.nbeats_model = NBEATS(params=params,scaler_x=self.scaler_x,scaler_y=self.scaler_y)

        # Train model
        self.nbeats_model.train(X_train, y_train, X_val, y_val)

        # Save model
        self.nbeats_model.save(os.path.join(models_path,'nbeats_model'))


    def train_nhits(self, X_train, y_train, X_val=None, y_val=None, params=None, feature_columns=None):
        """Train custom NHITS model"""
        print("Training custom NHITS model...")

        if params is None:
            params = {
                'n_in': 24*7,
                'n_out': 24,
                'n_features': X_train.shape[2],
                'n_blocks': [3,3,3,3 ],
                'mlp_units': [256, 256],
                'n_pool_kernel_size': [24, 8, 4, 1],
                'n_freq_downsample': [8, 4, 2, 1],
                'dropout_rate': 0.1,
                'learning_rate': 0.001,
                'epochs': 10,
                'batch_size': 32
            }

        self.nhits_model = NHITS(params=params,scaler_x=self.scaler_x,scaler_y=self.scaler_y)

        # Train model
        self.nhits_model.train(X_train, y_train,X_val=X_val, y_val=y_val)
        
        # Save model
        self.nhits_model.save(os.path.join(models_path,'nhits_model'))


    def train_xgboost(self, df, feature_columns, params, skip_size=skip_size, train_size=0.85,val_size=0.1,horizon=xgb_params['num_target']):
        """Train XGBoost model to predict multiple steps ahead"""
        print("Training multi-output XGBoost model...")

        # Ensures that lag features are created
        # add_consumption_features_bool=True
        # add_cross_features_bool=True

        X_train, X_val, X_test, y_train, y_val, y_test  = self.create_sequences_xgboost(df,feature_columns,skip_size, train_size,val_size,horizon)

        X_train_array = X_train.values.astype('float32')
        y_train_array = y_train.values.astype('float32')
        X_val_array = X_val.values.astype('float32')
        y_val_array = y_val.values.astype('float32')

        # Train using XGBoost's built-in multi-output
        dtrain = xgb.DMatrix(X_train_array, label=y_train_array)
        dval = xgb.DMatrix(X_val_array, label=y_val_array)

        params_multi = {
            **params,
            'objective': 'reg:squarederror',
            'eval_metric': ['rmse','mae'],
            'num_target': horizon  # Tell XGBoost we have multiple outputs
        }

        model = xgb.train(
            params_multi,
            dtrain,
            num_boost_round=500,
            evals=[(dtrain, 'train'), (dval, 'val')],
            early_stopping_rounds=50,
            verbose_eval=10
        )
        # Predict
        X_test_array = X_test.values
        dtest = xgb.DMatrix(X_test_array)
        model.save_model(os.path.join(models_path,'xgboost_model.xgb'))

        # Make predictions
        y_pred = model.predict(dtest)  # This returns (n_samples, horizon) shape

        # Convert predictions back to DataFrame if needed
        # y_pred = pd.DataFrame(y_pred,
        #              index=y_test.index,
        #              columns=[f'y_h{i+1}' for i in range(horizon)])
        return model, y_pred, y_test, X_test, feature_columns


    def evaluate_model(self, y_true, y_pred, model_name):
        """Evaluate model performance"""
        # Denormalize if scaler is available
    
        original_shape = y_true.shape

        # Convert to numpy arrays for reshaping
        y_true = y_true.to_numpy() if hasattr(y_true, 'values') else y_true
        y_pred = y_pred.to_numpy() if hasattr(y_pred, 'values') else y_pred
        
        # Store original shapes for reconstruction
        original_shape = y_true.shape if hasattr(y_true, 'shape') else y_true.shape
    
        # Denormalize if scaler is available
        if self.scaler_y is not None:
            # Reshape to 2D for inverse_transform, then back to original shape
            y_true_denorm = self.scaler_y.inverse_transform(y_true.reshape(-1, 1))
            y_pred_denorm = self.scaler_y.inverse_transform(y_pred.reshape(-1, 1))

            # Reshape back to original (samples, horizons) format
            y_true_denorm = y_true_denorm.reshape(original_shape)
            y_pred_denorm = y_pred_denorm.reshape(original_shape)
        else:
            y_true_denorm = y_true
            y_pred_denorm = y_pred

        # Calculate metrics per timestep (for each horizon)
        if len(original_shape) == 2 and original_shape[1] > 1:  # Multi-output case
            mae_per_timestep = np.mean(np.abs(y_true_denorm - y_pred_denorm), axis=0)
            rmse_per_timestep = np.sqrt(np.mean((y_true_denorm - y_pred_denorm) ** 2, axis=0))
            mape_per_timestep = np.mean(np.abs((y_true_denorm - y_pred_denorm) / (np.abs(y_true_denorm) + 1e-8)), axis=0) * 100

            print(f"\n{model_name} - Per Timestep Evaluation:")
            for i, (mae, rmse, mape) in enumerate(zip(mae_per_timestep, rmse_per_timestep, mape_per_timestep)):
                if i%6==0:
                    print(f"Hour {i+1}: MAE={mae:.4f}, RMSE={rmse:.4f}, MAPE={mape:.2f}%")

        # Overall metrics (flatten for overall scores)
        y_true_flat = y_true_denorm.flatten()
        y_pred_flat = y_pred_denorm.flatten()

        mae = mean_absolute_error(y_true_flat, y_pred_flat)
        rmse = np.sqrt(mean_squared_error(y_true_flat, y_pred_flat))
        mape = np.mean(np.abs((y_true_flat - y_pred_flat) / (np.abs(y_true_flat) + 1e-8))) * 100
        print(f"MAE={mae:.4f}\n RMSE={rmse:.4f}\n MAPE={mape:.2f}%")

        return {'MAE': f'{mae:.4f}', 'RMSE': f'{rmse:.4f}', 'MAPE': f'{mape:.2f}'}, y_true_denorm, y_pred_denorm


    def enable_hover_projections(self, ax, show_x_proj=True, show_y_proj=True,
                                date_format="%Y-%m-%d %H:%M", fmt_value="{:.2f} €"):
        """
        Attach an interactive hover cursor to `ax`. Shows annotation and optional
        projection lines on X and/or Y axes.

        Returns the mplcursors cursor object (so you can disconnect later if needed).
        """
        # Create projection lines but keep them hidden initially
        vline = ax.axvline(np.nan, ls='--', lw=0.8, alpha=0.8, visible=True)
        hline = ax.axhline(np.nan, ls='--', lw=0.8, alpha=0.8, visible=True)

        # cursor targets line artists and scatter collections in the axis
        artists = []
        # include lines and collections present in the axis
        artists.extend(ax.lines)
        artists.extend(ax.collections)

        cursor = mplcursors.cursor(artists, hover=True)

        @cursor.connect("add")
        def on_add(sel):
            x, y = sel.target  # target is (x, y) in data coordinates

            # try to format x as datetime if it's a matplotlib date float
            x_label = None
            try:
                # matplotlib stores dates as float days since epoch in some plots
                if isinstance(x, (float, np.floating)):
                    dt = mdates.num2date(x)
                    x_label = dt.strftime(date_format)
                else:
                    # try pandas conversion
                    x_label = pd.to_datetime(x).strftime(date_format)
            except Exception:
                x_label = str(x)

            sel.annotation.set_text(f"{x_label}\n{fmt_value.format(y) if isinstance(fmt_value, str) else fmt_value(y)}")

            # set and show projection lines
            if show_x_proj:
                vline.set_xdata(x)
                vline.set_visible(True)
            if show_y_proj:
                hline.set_ydata(y)
                hline.set_visible(True)

            # nice background
            sel.annotation.get_bbox_patch().set_alpha(0.9)
            sel.annotation.get_bbox_patch().set_boxstyle("round,pad=0.5")
            ax.figure.canvas.draw_idle()



        return cursor


    def plot_predictions(self, y_true, y_pred, dates, model_name, ax=None, horizon_to_plot=0,interactive=True):
        """Plot predictions vs actual values for multi-output"""
        if ax is None:
            fig, ax = plt.subplots(figsize=(12, 6))

        # For multi-output handle each horizon separately
        if len(y_true.shape) == 2 and y_true.shape[1] > 1:
            # Plot first horizon (1-hour ahead) as an example
            # horizon_to_plot = 0  # 1-hour ahead predictions

            # Ensure dates match the first dimension
            if len(dates) != len(y_true):
                # If dates are for the entire sequence, take corresponding subset
                dates_plot = dates[:len(y_true)]
            else:
                dates_plot = dates

            ax.plot(dates_plot, y_true[:, horizon_to_plot], label='Actual', alpha=0.7, linewidth=2)
            ax.plot(dates_plot, y_pred[:, horizon_to_plot], label=f'Predicted (Hour {horizon_to_plot+1})', alpha=0.7, linewidth=2)
        else:
            # Single output case
            ax.plot(dates, y_true, label='Actual', alpha=0.7, linewidth=2)
            ax.plot(dates, y_pred, label='Predicted', alpha=0.7, linewidth=2)

        ax.set_title(f'{model_name} - Actual vs Predicted')
        ax.set_xlabel('Date')
        ax.set_ylabel('Energy Price (€/MWh)')
        ax.legend()
        ax.grid(True, alpha=0.3)
        # if interactive:
            # abilita proiezioni sia su X che su Y
            # ritorna il cursor se vuoi tenerlo in scope (utile in notebook)
            # self._last_cursor = self.enable_hover_projections(ax, show_x_proj=True, show_y_proj=True)        
        plt.xticks(rotation=45)

        return ax


    def plot_multiple_horizons(self, y_true, y_pred, dates, model_name, horizons=[0, 5, 11, 23],interactive=True):
        """Plot predictions for multiple horizons"""
        fig, axes = plt.subplots(2, 2, figsize=(15, 10))
        axes = axes.flatten()

        for idx, horizon in enumerate(horizons):
            ax = axes[idx]

            # Plot last 100 points for clarity
            plot_range = slice(0, 100)

            ax.plot(dates[plot_range], y_true[plot_range, horizon],
                    label='Actual', alpha=0.7, linewidth=2)
            ax.plot(dates[plot_range], y_pred[plot_range, horizon],
                    label=f'Predicted', alpha=0.7, linewidth=2)

            ax.set_title(f'{model_name} - Horizon {horizon+1}h ahead')
            ax.set_xlabel('Date')
            ax.set_ylabel('Energy Price (€/MWh)')
            ax.legend()
            ax.grid(True, alpha=0.3)
            # if interactive:
            #     # abilita proiezioni sia su X che su Y
            #     # ritorna il cursor se vuoi tenerlo in scope (utile in notebook)
            #     self._last_cursor = self.enable_hover_projections(ax, show_x_proj=True, show_y_proj=True)
            plt.setp(ax.xaxis.get_majorticklabels(), rotation=45)

        plt.tight_layout()
        plt.show()


    def plot_prediction_sequences(self, y_true, y_pred, dates, model_name, window=24, n_sequences=5,interactive=False):
        """Plot complete window_h prediction sequences"""
        if window==24 :
            if n_sequences>7:
                n_sequences=7
            fig, axes = plt.subplots(n_sequences//2+n_sequences%2,2, figsize=(15, 3*n_sequences))
            n_sequences=n_sequences+n_sequences%2
            axes=axes.flatten()
        else:
            if n_sequences>2:
                n_sequences=2
            fig, axes = plt.subplots(n_sequences, figsize=(15, 4*n_sequences))

        if n_sequences == 1:
            axes = [axes]

        for i in range(n_sequences):
            ax = axes[i]

            # Get one complete prediction sequence
            sequence_idx = i*window   # Start of each 24h sequence

            # Create time points for the 24h horizon
            hours = np.arange(1, window+1)
            ax.plot(hours, y_true[sequence_idx, :], 'o-', label='Actual', alpha=0.7, linewidth=2, markersize=4)
            ax.plot(hours, y_pred[sequence_idx, :], 's-', label='Predicted', alpha=0.7, linewidth=2, markersize=4)

            sequence_date = dates[sequence_idx] if sequence_idx < len(dates) else f"Sequence {i+1}"
            ax.set_title(f'{model_name} - {window}h Prediction starting {sequence_date}')
            ax.set_xlabel('Hours Ahead')
            ax.set_ylabel('Energy Price (€/MWh)')
            ax.legend()
            ax.grid(True, alpha=0.3)
            ax.set_xticks(range(1, window+1, 2))
            # if interactive:
                # abilita proiezioni sia su X che su Y
                # ritorna il cursor se vuoi tenerlo in scope (utile in notebook)
                # self._last_cursor = self.enable_hover_projections(ax, show_x_proj=True, show_y_proj=True)

        plt.tight_layout()
        plt.show()


    def plot_prediction_heatmap(self, y_true, y_pred, model_name):
        """Plot heatmap of prediction errors across all horizons"""
        # Calculate absolute errors
        errors = np.abs(y_true - y_pred)

        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6))

        # Heatmap of errors
        im1 = ax1.imshow(errors.T, aspect='auto', cmap='YlOrRd', interpolation='nearest')
        ax1.set_xlabel('Sample Index')
        ax1.set_ylabel('Horizon (Hours Ahead)')
        ax1.set_title(f'{model_name} - Absolute Errors by Horizon')
        ax1.set_yticks(range(0, y_pred.shape[1], 6))
        ax1.set_yticklabels(range(1, y_pred.shape[1]+1, 6))
        plt.colorbar(im1, ax=ax1, label='Absolute Error')

        # Average error per horizon
        avg_errors = np.mean(errors, axis=0)
        ax2.bar(range(1, y_pred.shape[1]+1), avg_errors)
        ax2.set_xlabel('Horizon (Hours Ahead)')
        ax2.set_ylabel('Average Absolute Error')
        ax2.set_title(f'{model_name} - Average Error by Horizon')
        ax2.grid(True, alpha=0.3)

        plt.tight_layout()
        plt.show()


    def plot_shap_analysis(self, xgb_model, X_test, feature_names, horizons_to_plot=None, top_n=10, sample_idx=0):
        """Complete SHAP analysis in one function - calculates once, plots everything"""
        print("Calculating SHAP values for multi-output model...")

        # Calculate SHAP values ONCE
        explainer = shap.Explainer(xgb_model)
        shap_values = explainer(X_test)

        print(f"SHAP values shape: {shap_values.shape}")
        print(f"Features: {shap_values.shape[1]}, Horizons: {shap_values.shape[2]}")

        # Set default horizons to plot
        if horizons_to_plot is None:
            horizons_to_plot = [0, 1, 2, 3, 11, 23]  # 1h, 2h, 3h, 4h, 12h, 24h ahead

        # 1. Plot summary for each horizon
        print("\n--- Plotting Horizon-wise SHAP Summaries ---")
        for horizon in horizons_to_plot:
            print(f"Plotting Horizon {horizon + 1}h ahead...")

            plt.figure(figsize=(10, 8))
            print(shap_values.shape)

            shap.summary_plot(shap_values[:, :, horizon], X_test, feature_names=feature_names, show=False, plot_type="dot")
            plt.title(f'SHAP Feature Importance - {horizon + 1}h Ahead Forecast')
            plt.tight_layout()
            plt.savefig(f'shap_horizon_{horizon + 1}h.png', dpi=300, bbox_inches='tight')
            plt.show()


        # 2. Plot overall feature importance
        print("\n--- Plotting Overall Feature Importance ---")
        plt.figure(figsize=(12, 8))
        mean_abs_shap = np.mean(np.abs(shap_values.values), axis=(0, 2))
        print(len(feature_names), mean_abs_shap.shape)

        feature_importance = pd.DataFrame({'feature': feature_names,'importance': mean_abs_shap}).sort_values('importance', ascending=True)

        plt.barh(feature_importance['feature'][-20:], feature_importance['importance'][-20:])
        plt.title(f'Overall Feature Importance (Average across all {xgb_params['num_target']} horizons)')
        plt.xlabel('Mean |SHAP value|')
        plt.tight_layout()
        plt.savefig('shap_overall_importance.png', dpi=300, bbox_inches='tight')
        plt.show()



        # 3. Plot feature importance evolution across horizons
        print("\n--- Plotting Feature Importance Evolution ---")
        plt.figure(figsize=(12, 8))

        # Get top features
        overall_importance = np.mean(np.abs(shap_values.values), axis=(0, 2))
        top_indices = np.argsort(overall_importance)[-top_n:]
        top_features = [feature_names[i] for i in top_indices]

        # Calculate importance per horizon
        horizon_importance = np.mean(np.abs(shap_values.values), axis=0)
        horizons = range(1, xgb_params['num_target']+1)

        for i, feature_idx in enumerate(top_indices):
            plt.plot(horizons, horizon_importance[feature_idx, :],
                    'o-', label=top_features[i], linewidth=2, markersize=4)

        plt.xlabel('Prediction Horizon (Hours Ahead)')
        plt.ylabel('Mean |SHAP value|')
        plt.title('Feature Importance Evolution Across Prediction Horizons')
        plt.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
        plt.grid(True, alpha=0.3)
        plt.xticks(range(1, xgb_params['num_target']+1, 2))
        plt.tight_layout()
        plt.savefig('shap_horizon_evolution.png', dpi=300, bbox_inches='tight')
        plt.show()


        # # 4. Plot waterfall for multiple horizons
        # print("\n--- Plotting Waterfall Charts ---")
        # fig, axes = plt.subplots(2, figsize=(15, 12))
        # axes = axes.flatten()

        # waterfall_horizons = [0, 23]  # 1h,  24h ahead

        # for idx, horizon in enumerate(waterfall_horizons):
        #     plt.sca(axes[idx])
        #     shap.plots.waterfall(shap_values[sample_idx, :, horizon],
        #                     max_display=15, show=False)
        #     plt.title(f'Waterfall Plot - Horizon {horizon + 1}h Ahead\n(Sample {sample_idx})')

        # plt.tight_layout()
        # plt.savefig('shap_waterfall_multioutput.png', dpi=300, bbox_inches='tight')
        # plt.show()

        print("SHAP analysis complete!")
        return shap_values  # Return in case you want to use them later


def model_training(forecaster, df, feature_columns, models_to_run=['NHITS'], 
                   save_dir=models_path, skip_size=skip_size, train_size=train_size, val_size=val_size, horizon=xgb_params['num_target'],
                   nbeats_params_local=None, nhits_params_local=None, xgb_params_local=None):
    """
    Train one or more selected models, evaluate, plot results, and save models+scalers.
    - forecaster: PriceForecaster instance
    - df: processed and normalized dataframe (use forecaster.normalize_data(..., fit_scaler=True) before calling)
    - feature_columns: list of feature names
    - models_to_run: list containing any of ['XGBoost','NBEATS','NHITS']
    - save_dir: where to save models and scalers
    """
    os.makedirs(save_dir, exist_ok=True)
    results = {}
    if models_to_run is None :
        models_to_run=['NHITS']


    # XGBoost
    if 'XGBoost' in models_to_run:
        print(">>> Running XGBoost")
        params=xgb_params_local if xgb_params_local else xgb_params
        # Train
        if add_price_features_bool == False:
            print('XGBoost ha bisogno di più features per funzionare, creazione di feature aggiuntive...')
            df=forecaster.feature_engineer.add_price_features(df)
            feature_columns =[col for col in df.columns if col not in ['ds', 'y']]
            df = forecaster.normalize_data(df, feature_columns, fit_scaler=True)
            print('Features create:', len(feature_columns))
        if 'y_normalized' not in feature_columns: 
            feature_columns = ['y_normalized'] + feature_columns

        print(params)
        start_time = time.time()
        xgb_model, xgb_pred, xgb_test, X_test_xgb, xgb_features = forecaster.train_xgboost(
            df, feature_columns, params=params,
            skip_size=skip_size, train_size=train_size, val_size=val_size, horizon=params['num_target']
        )

        end_time = time.time()
        print(f"Training time: {end_time - start_time:.2f} seconds")

        # Save scalers (xgboost train_xgboost doesn't save them currently)
        with open(os.path.join(save_dir, 'xgboost_model_scaler_x.pkl'), 'wb') as f:
            pickle.dump(forecaster.scaler_x, f)
        with open(os.path.join(save_dir, 'xgboost_model_scaler_y.pkl'), 'wb') as f:
            pickle.dump(forecaster.scaler_y, f)

        # Evaluate & denorm
        xgb_metrics, xgb_true_denorm, xgb_pred_denorm = forecaster.evaluate_model(
            xgb_test.values, xgb_pred, "XGBoost"
        )
        print(params)

        # Plot
        dates = df['ds'].iloc[-len(xgb_true_denorm):].values

        forecaster.plot_multiple_horizons(xgb_true_denorm, xgb_pred_denorm, dates, "XGBoost")
        forecaster.plot_prediction_sequences(xgb_true_denorm, xgb_pred_denorm, dates, "XGBoost",window=xgb_params['num_target'], n_sequences=n_windows_to_plot_xgboost)
        forecaster.plot_prediction_heatmap(xgb_true_denorm, xgb_pred_denorm,  "XGBoost")
        forecaster.plot_shap_analysis(xgb_model, X_test_xgb.iloc[:100], xgb_features,horizons_to_plot=[0,23])#, 5, 11
        
        # Save model (xgboost)
        xgb_model.save_model(os.path.join(save_dir, 'xgboost_model.xgb'))

        results['XGBoost'] = {'metrics': xgb_metrics, 'model_path': os.path.join(save_dir, 'xgboost_model.xgb')}

    # NBEATS
    if 'NBEATS' in models_to_run:
        print(">>> Running NBEATS")
        # Create time-based sequences (your function returns X_tr, y_tr, X_v, y_v, X_te, y_te). 
        params=nbeats_params_local if nbeats_params_local else nbeats_params
        X_tr, y_tr, X_v, y_v, X_te, y_te = forecaster.prepare_sequences_time_based(
            df, feature_columns,
            n_in=params['n_in'],
            n_out=params['n_out'],
            step=params['step'],
            skip_size=skip_size, train_ratio=train_size, val_ratio=val_size
        )


        
        # update n_features
        params['n_features'] = X_tr.shape[2]
        
        start_time = time.time()

        # Train
        print(params)
        forecaster.train_nbeats(X_tr, y_tr, X_v, y_v, params=params)  # uses your existing train_nbeats. 

        end_time = time.time()
        print(f"Training time: {end_time - start_time:.2f} seconds")
        nbeats_pred = forecaster.nbeats_model.predict(X_te)
        nbeats_metrics, nbeats_true_denorm, nbeats_pred_denorm = forecaster.evaluate_model(y_te, nbeats_pred, "NBEATS")
        print(params)

        dates = df['ds'].iloc[-len(nbeats_true_denorm):].values
        forecaster.plot_multiple_horizons(nbeats_true_denorm, nbeats_pred_denorm, dates, "NBEATS")
        forecaster.plot_prediction_sequences(nbeats_true_denorm, nbeats_pred_denorm, dates, "NBEATS", window= params['n_out'], n_sequences=n_windows_to_plot_nbeats)
        forecaster.plot_prediction_heatmap(nbeats_true_denorm, nbeats_pred_denorm, "NBEATS")

        # Save PyTorch model & scalers (PyTorchForecastingModel.save already saves scalers). 
        forecaster.nbeats_model.save(os.path.join(save_dir, 'nbeats_model'))
        results['NBEATS'] = {'metrics': nbeats_metrics, 'model_path': os.path.join(save_dir, 'nbeats_model')}

    # NHITS
    if 'NHITS' in models_to_run or not results: 
        print(">>> Running NHITS")

        params=nhits_params_local if nhits_params_local else nhits_params
        X_tr, y_tr, X_v, y_v, X_te, y_te = forecaster.prepare_sequences_time_based(
            df, feature_columns,
            n_in=params['n_in'],
            n_out=params['n_out'],
            step=params['step'],
            skip_size=skip_size, train_ratio=train_size, val_ratio=val_size
        )

        params['n_features'] = X_tr.shape[2]

        start_time = time.time()
        # Train
        print(params)
        forecaster.train_nhits(X_tr, y_tr, X_v, y_v, params=params)  # uses your existing train_nhits. 

        end_time = time.time()
        print(f"Training time: {end_time - start_time:.2f} seconds")
        nhits_pred = forecaster.nhits_model.predict(X_te)
        print(params)
        nhits_metrics, nhits_true_denorm, nhits_pred_denorm = forecaster.evaluate_model(y_te, nhits_pred, "NHITS")

        dates = df['ds'].iloc[-len(nhits_true_denorm):].values

        forecaster.plot_multiple_horizons(nhits_true_denorm, nhits_pred_denorm, dates, "NHITS")
        forecaster.plot_prediction_sequences(nhits_true_denorm, nhits_pred_denorm, dates, "NHITS", window= params['n_out'], n_sequences=n_windows_to_plot_nhits)
        forecaster.plot_prediction_heatmap(nhits_true_denorm, nhits_pred_denorm, "NHITS")

        forecaster.nhits_model.save(os.path.join(save_dir, 'nhits_model'))
        results['NHITS'] = {'metrics': nhits_metrics, 'model_path': os.path.join(save_dir, 'nhits_model')}


  
    # Print summary
    print("\n=== Experiment summary ===")
    for m, info in results.items():
        print(f"{m}: {info['metrics']}")
    return results


def load_and_predict(forecaster, df_raw, model_key='XGBoost', model_path=None, save_dir=models_path, skip_set_size=0.0, train_set_size=0.8, val_set_size=0.1, horizon=24, show_plots=True,show_intervals=True,confidence_levels=[0.8, 0.9],use_quantiles=False):    
    """
    Load a saved model and scalers, run predictions on latest test-slice, evaluate & plot.
    - forecaster: PriceForecaster instance (fresh instance recommended)
    - df_raw: raw df (will be processed like in training)
    - model_key: 'XGBoost' or 'NBEATS' or 'NHITS'
    - model_path: path to the saved model file (if None, default filename is used)
    """
    # Prepare features and scalers
    df_proc, feat_cols = forecaster.prepare_features(df_raw)
    # load scalers if exist
    scalar_x_path = os.path.join(save_dir, f'{model_key.lower()}_model_scaler_x.pkl')
    scalar_y_path = os.path.join(save_dir, f'{model_key.lower()}_model_scaler_y.pkl')
    if os.path.exists(scalar_x_path):
        with open(scalar_x_path, 'rb') as f: forecaster.scaler_x = pickle.load(f)
    if os.path.exists(scalar_y_path):
        with open(scalar_y_path, 'rb') as f: forecaster.scaler_y = pickle.load(f)

    df_norm = forecaster.normalize_data(df_proc, feat_cols, fit_scaler=False)

    if os.path.exists(scalar_x_path):
        with open(scalar_x_path, 'rb') as f: 
            forecaster.scaler_x = pickle.load(f)
    if os.path.exists(scalar_y_path):
        with open(scalar_y_path, 'rb') as f: 
            forecaster.scaler_y = pickle.load(f)

    df_norm = forecaster.normalize_data(df_proc, feat_cols, fit_scaler=False)

    if model_key == 'XGBoost':
        # XGBoost needs price features
        if add_price_features_bool == False:
            print('XGBoost needs more features, creating additional features...')
            df_proc = forecaster.feature_engineer.add_price_features(df_proc)
            feat_cols = [col for col in df_proc.columns if col not in ['ds', 'y']]
            df_norm = forecaster.normalize_data(df_proc, feat_cols, fit_scaler=True)
            print('Features created:', len(feat_cols))
        
        if 'y_normalized' not in feat_cols: 
            feat_cols = ['y_normalized'] + feat_cols

        _, _, X_test, _, _, y_test = forecaster.create_sequences_xgboost(
            df_norm, feat_cols, skip_size=skip_set_size, 
            train_size=train_set_size, val_size=val_set_size, 
            horizon=xgb_params['num_target']
        )
        
        # load xgboost model
        if model_path is None:
            model_path = os.path.join(save_dir, 'xgboost_model.xgb')
        
        xgb_model = xgb.Booster()
        xgb_model.load_model(model_path)
        
        # Prepare test data as DMatrix
        X_test_array = X_test.values
        dtest = xgb.DMatrix(X_test_array)
        
        # Predict
        y_pred = xgb_model.predict(dtest)

        metrics, y_true_denorm, y_pred_denorm = forecaster.evaluate_model(
            y_test.values, y_pred, "XGBoost_(loaded)"
        )
        dates = df_norm['ds'].iloc[-len(y_true_denorm):].values
        window = xgb_params['num_target']
        n_windows = n_windows_to_plot_xgboost
        last_dates = df_norm['ds'].iloc[-1]


    elif model_key.upper() in ('NBEATS','NHITS'):
        n_in = nbeats_params['n_in'] if model_key=='NBEATS' else nhits_params['n_in']
        n_out = nbeats_params['n_out'] if model_key=='NBEATS' else nhits_params['n_out']
        params=nbeats_params if model_key=='NBEATS' else nhits_params
        X_tr, y_tr, X_v, y_v, X_te, y_te = forecaster.prepare_sequences_time_based(df_norm, feat_cols, n_in=n_in, n_out=n_out, step=1, skip_size=skip_set_size, train_ratio=train_set_size, val_ratio=val_set_size)
        if model_path is None:
            model_path = os.path.join(save_dir, f"{model_key.lower()}_model")
        # load NBEATS or NHITS model
        if model_key == 'NBEATS':
            params['n_features'] = X_tr.shape[2]
            forecaster.nbeats_model = NBEATS(params=params,scaler_x=forecaster.scaler_x, scaler_y=forecaster.scaler_y)
            forecaster.nbeats_model.load(model_path)
            y_pred = forecaster.nbeats_model.predict(X_te)
            n_windows=n_windows_to_plot_nbeats
        else:
            params['n_features'] = X_tr.shape[2]
            forecaster.nhits_model = NHITS(params=params,scaler_x=forecaster.scaler_x, scaler_y=forecaster.scaler_y)
            forecaster.nhits_model.load(model_path)
            y_pred = forecaster.nhits_model.predict(X_te)
            n_windows=n_windows_to_plot_nhits

        metrics, y_true_denorm, y_pred_denorm = forecaster.evaluate_model(y_te, y_pred, f"{model_key}_(loaded)")
        dates = df_norm['ds'].iloc[-len(y_true_denorm):].values

        last_dates = df_norm['ds'].iloc[-1]

    else:
        raise ValueError(f"Unknown model_key:{model_key}. Check if it has been trained")

    if show_plots:
        if model_key == 'XGBoost':
            window = xgb_params['num_target']
            n_windows = n_windows_to_plot_xgboost
        elif model_key == 'NBEATS':
            window = nbeats_params['n_out']
            n_windows = n_windows_to_plot_nbeats
        elif model_key == 'NHITS':
            window = nhits_params['n_out']
            n_windows = n_windows_to_plot_nhits
        # Plot with intervals
        if show_intervals:
            forecaster.plot_predictions_with_intervals(y_true_denorm, y_pred_denorm, dates, f"{model_key}_(loaded)",confidence_levels=confidence_levels,use_quantiles=use_quantiles)
                
            forecaster.plot_prediction_sequences_with_intervals(y_true_denorm, y_pred_denorm, dates,f"{model_key}_(loaded)",window=window,n_sequences=n_windows,confidence_levels=confidence_levels,use_quantiles=use_quantiles)
                
            forecaster.plot_interval_coverage(y_true_denorm, y_pred_denorm,f"{model_key}_(loaded)",confidence_levels=confidence_levels,use_quantiles=use_quantiles)
        else:
            # Original plots without intervals
            forecaster.plot_prediction_sequences(y_true_denorm, y_pred_denorm, dates,f"{model_key}_(loaded)",window=window,n_sequences=n_windows)
            forecaster.plot_prediction_heatmap(y_true_denorm, y_pred_denorm, f"{model_key}_(loaded)")
    
    return metrics, y_true_denorm, y_pred_denorm,last_dates

# The function to call for starting the program
def run():

    # Prepare forecaster and data
    forecaster = PriceForecaster(datasets_path=datasets_path)

    df = forecaster.load_and_prepare_data()
    df_proc, feat_cols = forecaster.prepare_features(df)
    df_norm = forecaster.normalize_data(df_proc, feat_cols, fit_scaler=True)

    # Models_to_run currently set on 'NHITS'
    results = model_training(forecaster, df_norm, feat_cols, models_to_run=models_to_run, save_dir=models_path)


    # Later: load saved model and predict on fresh data (Features has to be the same)
    model_key=models_to_run[0] # Currently set on 'NHITS'
    show_plots=True            # Get plots of predicted values 
    forecaster2 = PriceForecaster(datasets_path=datasets_path)
    df_new = forecaster2.load_and_prepare_data()   # or new dataset
    df_new, feat_cols = forecaster2.prepare_features(df_new)
    metrics, y_true, y_pred, date= load_and_predict(forecaster2, df_new, model_key=model_key, save_dir=models_path, show_plots=show_plots, show_intervals=True, confidence_levels=[0.7,0.8], use_quantiles=False)
    return y_pred[-1:],date

if __name__ == '__main__':
    predictions, date = run()
    print(f'next {n_out} hours, starting from {date}: {predictions}')
