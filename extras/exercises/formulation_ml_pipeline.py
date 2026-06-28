# =============================================================================
# Formulation Predictive Modeling Pipeline
# Acrylic Emulsion System - Multi-Output ML Framework
# =============================================================================

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import warnings
warnings.filterwarnings('ignore')

# ── DOE ──────────────────────────────────────────────────────────────────────
from pyDOE2 import lhs                        # Latin Hypercube Sampling (Space-Filling)
from scipy.stats.qmc import LatinHypercube    # scipy alternative

# ── Data / Preprocessing ─────────────────────────────────────────────────────
from sklearn.preprocessing import StandardScaler, MinMaxScaler
from sklearn.impute import SimpleImputer, KNNImputer
from sklearn.pipeline import Pipeline
from sklearn.model_selection import train_test_split, cross_val_score, KFold

# ── Models ───────────────────────────────────────────────────────────────────
from sklearn.multioutput import MultiOutputRegressor, RegressorChain
from sklearn.linear_model import Ridge, Lasso, ElasticNet
from sklearn.tree import DecisionTreeRegressor
from sklearn.ensemble import (RandomForestRegressor, GradientBoostingRegressor,
                               ExtraTreesRegressor, VotingRegressor)
from sklearn.svm import SVR
from lightgbm import LGBMRegressor
from xgboost import XGBRegressor

# ── Metrics ──────────────────────────────────────────────────────────────────
from sklearn.metrics import r2_score, mean_squared_error, mean_absolute_error

# ── Explainability ───────────────────────────────────────────────────────────
import shap

# =============================================================================
# SECTION 1: DOE — Design of Experiments
# =============================================================================
print("=" * 60)
print("SECTION 1: DOE — Design of Experiments")
print("=" * 60)

# Feature names: monomer content (wt%) + key additives
feature_names = [
    'BA_pct',        # Butyl Acrylate        — soft monomer, controls Tg & flexibility
    'MMA_pct',       # Methyl Methacrylate   — hard monomer, hardness & weather resistance
    'AA_pct',        # Acrylic Acid          — adhesion & colloidal stability
    'HEMA_pct',      # Hydroxyethyl MMA      — crosslink sites, water resistance
    'ST_pct',        # Styrene               — cost reduction, gloss
    'AM_pct',        # Acrylamide            — wet adhesion strength
    'CaCO3_pct',     # Calcium Carbonate     — filler, cost & opacity
    'TiO2_pct',      # Titanium Dioxide      — whiteness & opacity
    'Crosslinker_pct',  # Crosslinker        — network density
    'Coalescent_pct',   # Coalescent Agent   — film formation aid
]

# Target names (multi-output)
target_names = [
    'Peel_Strength',       # N/mm
    'Shear_Strength',      # N/mm²
    'Open_Time',           # minutes
    'Wet_Scrub_Resistance',# cycles
    'Water_Absorption',    # %
]

# ── 1a. Space-Filling DOE: Latin Hypercube Sampling ──────────────────────────
print("\n[Method 1] Space-Filling: Latin Hypercube Sampling (LHS)")
print("  → Used when budget is sufficient; maximizes coverage of design space")

n_experiments_lhs = 80
n_features = len(feature_names)

# Define bounds [min, max] for each feature (wt%)
bounds = np.array([
    [30, 55],   # BA
    [15, 35],   # MMA
    [1,  5],    # AA
    [1,  5],    # HEMA
    [5,  20],   # ST
    [0.5, 3],   # AM
    [0,  15],   # CaCO3
    [2,  10],   # TiO2
    [0.5, 3],   # Crosslinker
    [1,  5],    # Coalescent
])

np.random.seed(42)
lhs_unit = lhs(n_features, samples=n_experiments_lhs, criterion='maximin')
# Scale from [0,1] to actual bounds
X_doe_lhs = lhs_unit * (bounds[:, 1] - bounds[:, 0]) + bounds[:, 0]
df_doe_lhs = pd.DataFrame(X_doe_lhs, columns=feature_names)
print(f"  LHS design shape: {df_doe_lhs.shape}")

# ── 1b. Budget-Constrained DOE: D-Optimal (conceptual note) ──────────────────
print("\n[Method 2] Budget-Constrained: D-Optimal Design")
print("  → Used when experiment count is limited; maximizes information per run")
print("  → Typically implemented via JMP, Design-Expert, or pyDOE3 d_optimal()")
print("  → Criterion: maximize det(X'X) — minimizes variance of parameter estimates")
print("  → In Python: from pyDOE3 import d_optimal  (or use R's AlgDesign package)")

# =============================================================================
# SECTION 2: Simulate Experimental Results (Mock Data)
# =============================================================================
print("\n" + "=" * 60)
print("SECTION 2: Generate Mock Experimental Data")
print("=" * 60)

def simulate_targets(X):
    """
    Physics-informed mock target generation.
    BA↑ → softer → lower shear, higher open_time
    MMA↑ → harder → higher shear & scrub resistance
    AA↑ → better adhesion → higher peel
    Crosslinker↑ → lower water absorption
    """
    n = len(X)
    BA  = X[:, 0]; MMA = X[:, 1]; AA  = X[:, 2]
    HEMA= X[:, 3]; CL  = X[:, 8]

    noise = lambda scale: np.random.normal(0, scale, n)

    peel   = 2.0 + 0.04*AA  + 0.01*BA  - 0.005*MMA + noise(0.15)
    shear  = 1.5 + 0.03*MMA - 0.01*BA  + 0.02*HEMA + noise(0.12)
    open_t = 8.0 + 0.10*BA  - 0.05*MMA + noise(1.0)
    scrub  = 800 + 5*MMA    - 3*BA     + 10*CL     + noise(30)
    water  = 12  - 0.5*CL   - 0.3*HEMA + 0.1*BA    + noise(0.8)

    return np.column_stack([peel, shear, open_t, scrub, water])

Y_raw = simulate_targets(X_doe_lhs)

# Combine into full dataframe
df_full = df_doe_lhs.copy()
for i, name in enumerate(target_names):
    df_full[name] = Y_raw[:, i]

# Inject some missing values (realistic)
np.random.seed(7)
for col in target_names:
    idx_missing = np.random.choice(df_full.index, size=3, replace=False)
    df_full.loc[idx_missing, col] = np.nan

print(f"Full dataset shape: {df_full.shape}")
print(f"Missing values:\n{df_full.isnull().sum()}")

# =============================================================================
# SECTION 3: Data Cleaning & Preprocessing
# =============================================================================
print("\n" + "=" * 60)
print("SECTION 3: Data Cleaning & Preprocessing")
print("=" * 60)

X_raw = df_full[feature_names].values
Y_raw_df = df_full[target_names]

# ── 3a. Feature Engineering: Fox Equation for Tg ─────────────────────────────
print("\n[Feature Engineering] Adding derived feature: Theoretical Tg (Fox Equation)")
# Fox Equation: 1/Tg = sum(wi / Tgi)
# Tg values (K) for each monomer
Tg_values = {
    'BA': 219,   # K  (-54°C)
    'MMA': 378,  # K  (105°C)
    'AA': 379,   # K  (106°C)
    'HEMA': 328, # K  (55°C)
    'ST': 373,   # K  (100°C)
    'AM': 438,   # K  (165°C)
}
monomer_cols = ['BA_pct','MMA_pct','AA_pct','HEMA_pct','ST_pct','AM_pct']
Tg_K_list = [219, 378, 379, 328, 373, 438]

df_features = df_full[feature_names].copy()
monomer_sum = df_features[monomer_cols].sum(axis=1)
fox_inv = sum(df_features[col] / monomer_sum / Tg_K
              for col, Tg_K in zip(monomer_cols, Tg_K_list))
df_features['Tg_theoretical_K'] = 1.0 / fox_inv
df_features['SoftHard_ratio'] = (df_features['BA_pct'] + df_features['ST_pct']) / \
                                  (df_features['MMA_pct'] + df_features['HEMA_pct'] + 1e-6)

feature_names_ext = feature_names + ['Tg_theoretical_K', 'SoftHard_ratio']
print(f"  Extended feature count: {len(feature_names_ext)}")

# ── 3b. Missing Value Imputation ──────────────────────────────────────────────
print("\n[Missing Values] Strategy: KNN Imputation for targets")
knn_imputer = KNNImputer(n_neighbors=5)
Y_imputed = knn_imputer.fit_transform(Y_raw_df)
Y_df = pd.DataFrame(Y_imputed, columns=target_names)
print("  KNN imputation complete — no missing values remain")

X_df = df_features[feature_names_ext].copy()

# ── 3c. Outlier Detection (IQR method) ───────────────────────────────────────
print("\n[Outlier Detection] IQR method on targets")
def flag_outliers_iqr(df, cols, k=2.5):
    mask = pd.Series([False] * len(df))
    for col in cols:
        Q1, Q3 = df[col].quantile(0.25), df[col].quantile(0.75)
        IQR = Q3 - Q1
        mask |= (df[col] < Q1 - k*IQR) | (df[col] > Q3 + k*IQR)
    return mask

outlier_mask = flag_outliers_iqr(Y_df, target_names)
print(f"  Outliers flagged: {outlier_mask.sum()} rows (kept for now, flagged for review)")

# =============================================================================
# SECTION 4: Descriptive Analysis & Visualization
# =============================================================================
print("\n" + "=" * 60)
print("SECTION 4: Descriptive Analysis & Visualization")
print("=" * 60)

fig, axes = plt.subplots(2, 3, figsize=(16, 10))
fig.suptitle("Descriptive Analysis: Target Distributions", fontsize=14, fontweight='bold')

for i, (col, ax) in enumerate(zip(target_names, axes.flatten())):
    ax.hist(Y_df[col], bins=15, color='#4C72B0', edgecolor='white', alpha=0.85)
    ax.axvline(Y_df[col].mean(), color='red', linestyle='--', lw=1.5,
               label=f'Mean: {Y_df[col].mean():.2f}')
    ax.axvline(Y_df[col].median(), color='green', linestyle='--', lw=1.5,
               label=f'Median: {Y_df[col].median():.2f}')
    ax.set_title(col, fontweight='bold')
    ax.legend(fontsize=8)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)

axes.flatten()[-1].set_visible(False)
plt.tight_layout()
plt.savefig('/mnt/data/01_target_distributions.png', dpi=150, bbox_inches='tight')
plt.close()
print("  Saved: 01_target_distributions.png")

# Correlation heatmap
fig, ax = plt.subplots(figsize=(14, 11))
corr_df = pd.concat([X_df[feature_names_ext[:10]], Y_df], axis=1)
corr_matrix = corr_df.corr()
mask = np.triu(np.ones_like(corr_matrix, dtype=bool))
sns.heatmap(corr_matrix, mask=mask, annot=True, fmt='.2f', cmap='RdBu_r',
            center=0, linewidths=0.4, ax=ax, annot_kws={'size': 7})
ax.set_title('Feature–Target Correlation Matrix', fontweight='bold', fontsize=13)
plt.tight_layout()
plt.savefig('/mnt/data/02_correlation_heatmap.png', dpi=150, bbox_inches='tight')
plt.close()
print("  Saved: 02_correlation_heatmap.png")

# =============================================================================
# SECTION 5: Train/Test Split + Scaling
# =============================================================================
print("\n" + "=" * 60)
print("SECTION 5: Train/Test Split + Feature Scaling")
print("=" * 60)

X = X_df.values
Y = Y_df.values

X_train, X_test, Y_train, Y_test = train_test_split(
    X, Y, test_size=0.2, random_state=42)

scaler = StandardScaler()
X_train_sc = scaler.fit_transform(X_train)
X_test_sc  = scaler.transform(X_test)

print(f"  Train: {X_train_sc.shape}, Test: {X_test_sc.shape}")

# =============================================================================
# SECTION 6: Multi-Output Model Loop
# =============================================================================
print("\n" + "=" * 60)
print("SECTION 6: Multi-Output Model Comparison Loop")
print("=" * 60)
print("  sklearn.multioutput.MultiOutputRegressor wraps any single-output")
print("  estimator to handle multiple targets independently.")
print("  RegressorChain models targets sequentially (uses previous predictions as features).")

# Base models dict
base_models = {
    'Ridge':           Ridge(alpha=1.0),
    'Lasso':           Lasso(alpha=0.01),
    'ElasticNet':      ElasticNet(alpha=0.01, l1_ratio=0.5),
    'DecisionTree':    DecisionTreeRegressor(max_depth=5, random_state=42),
    'RandomForest':    RandomForestRegressor(n_estimators=100, random_state=42),
    'ExtraTrees':      ExtraTreesRegressor(n_estimators=100, random_state=42),
    'GradientBoosting':GradientBoostingRegressor(n_estimators=100, random_state=42),
    'XGBoost':         XGBRegressor(n_estimators=100, random_state=42, verbosity=0),
    'LightGBM':        LGBMRegressor(n_estimators=100, random_state=42, verbose=-1),
}

results = {}
kf = KFold(n_splits=5, shuffle=True, random_state=42)

for name, base_est in base_models.items():
    # Wrap with MultiOutputRegressor
    model = MultiOutputRegressor(base_est)
    model.fit(X_train_sc, Y_train)
    Y_pred = model.predict(X_test_sc)

    r2_per_target  = [r2_score(Y_test[:, i], Y_pred[:, i]) for i in range(Y.shape[1])]
    rmse_per_target= [np.sqrt(mean_squared_error(Y_test[:, i], Y_pred[:, i]))
                      for i in range(Y.shape[1])]

    results[name] = {
        'model': model,
        'R2_mean': np.mean(r2_per_target),
        'R2_per_target': dict(zip(target_names, r2_per_target)),
        'RMSE_per_target': dict(zip(target_names, rmse_per_target)),
    }
    print(f"  {name:<20} | Mean R²: {np.mean(r2_per_target):.4f}")

# =============================================================================
# SECTION 7: Results Comparison Table
# =============================================================================
print("\n" + "=" * 60)
print("SECTION 7: Results Comparison")
print("=" * 60)

results_df = pd.DataFrame({
    name: {**v['R2_per_target'], 'Mean_R2': v['R2_mean']}
    for name, v in results.items()
}).T.sort_values('Mean_R2', ascending=False)

print(results_df.round(4).to_string())

# Bar chart: Mean R² comparison
fig, ax = plt.subplots(figsize=(12, 6))
colors = ['#2ecc71' if v == results_df['Mean_R2'].max() else '#4C72B0'
          for v in results_df['Mean_R2']]
bars = ax.barh(results_df.index, results_df['Mean_R2'], color=colors, edgecolor='white')
for bar in bars:
    w = bar.get_width()
    ax.text(w + 0.005, bar.get_y() + bar.get_height()/2,
            f'{w:.4f}', va='center', fontsize=9)
ax.set_xlabel('Mean R² (across all targets)')
ax.set_title('Model Comparison — Multi-Output R²', fontweight='bold')
ax.axvline(0.8, color='red', linestyle='--', lw=1, label='R²=0.80 threshold')
ax.legend()
ax.spines['top'].set_visible(False)
ax.spines['right'].set_visible(False)
plt.tight_layout()
plt.savefig('/mnt/data/03_model_comparison.png', dpi=150, bbox_inches='tight')
plt.close()
print("\n  Saved: 03_model_comparison.png")

# =============================================================================
# SECTION 8: Per-Target Heatmap (which model wins per target)
# =============================================================================
r2_matrix = pd.DataFrame(
    {name: v['R2_per_target'] for name, v in results.items()}
).T

fig, ax = plt.subplots(figsize=(10, 7))
sns.heatmap(r2_matrix, annot=True, fmt='.3f', cmap='YlGn',
            linewidths=0.5, ax=ax, vmin=0, vmax=1)
ax.set_title('R² per Model per Target\n(→ basis for per-target model selection)', fontweight='bold')
plt.tight_layout()
plt.savefig('/mnt/data/04_r2_per_target_heatmap.png', dpi=150, bbox_inches='tight')
plt.close()
print("  Saved: 04_r2_per_target_heatmap.png")

# =============================================================================
# SECTION 9: Ensemble — Per-Target Best Model Selection
# =============================================================================
print("\n" + "=" * 60)
print("SECTION 9: Ensemble Strategy — Best Model per Target")
print("=" * 60)
print("  Observation: different algorithms excel on different targets.")
print("  Strategy: select the best-performing model per target, then combine.")

best_per_target = r2_matrix.idxmax(axis=0)
print("\n  Best model per target:")
for t, m in best_per_target.items():
    print(f"    {t:<25} → {m}  (R²={r2_matrix.loc[m, t]:.4f})")

# Build ensemble predictions by selecting best model per target
Y_pred_ensemble = np.zeros_like(Y_test, dtype=float)
for i, target in enumerate(target_names):
    best_model_name = best_per_target[target]
    best_model = results[best_model_name]['model']
    Y_pred_ensemble[:, i] = best_model.predict(X_test_sc)[:, i]

# Evaluate ensemble
ensemble_r2 = [r2_score(Y_test[:, i], Y_pred_ensemble[:, i]) for i in range(len(target_names))]
ensemble_rmse = [np.sqrt(mean_squared_error(Y_test[:, i], Y_pred_ensemble[:, i]))
                 for i in range(len(target_names))]

print("\n  Ensemble Performance:")
for t, r2, rmse in zip(target_names, ensemble_r2, ensemble_rmse):
    print(f"    {t:<25} R²={r2:.4f}  RMSE={rmse:.4f}")
print(f"\n  Ensemble Mean R²: {np.mean(ensemble_r2):.4f}")

# =============================================================================
# SECTION 10: SHAP Feature Importance (LightGBM, first target)
# =============================================================================
print("\n" + "=" * 60)
print("SECTION 10: SHAP Feature Importance (LightGBM → Peel Strength)")
print("=" * 60)

lgbm_multi = results['LightGBM']['model']
lgbm_single = lgbm_multi.estimators_[0]   # estimator for target[0] = Peel_Strength

explainer = shap.TreeExplainer(lgbm_single)
shap_values = explainer.shap_values(X_test_sc)

fig, ax = plt.subplots(figsize=(10, 6))
shap.summary_plot(shap_values, X_test_sc,
                  feature_names=feature_names_ext,
                  plot_type='bar', show=False)
plt.title('SHAP Feature Importance — Peel Strength (LightGBM)', fontweight='bold')
plt.tight_layout()
plt.savefig('/mnt/data/05_shap_importance.png', dpi=150, bbox_inches='tight')
plt.close()
print("  Saved: 05_shap_importance.png")

# =============================================================================
# SECTION 11: Actual vs Predicted Plot
# =============================================================================
fig, axes = plt.subplots(1, len(target_names), figsize=(20, 4))
fig.suptitle('Actual vs Predicted — Ensemble Model', fontweight='bold')

for i, (target, ax) in enumerate(zip(target_names, axes)):
    ax.scatter(Y_test[:, i], Y_pred_ensemble[:, i],
               alpha=0.7, color='#4C72B0', edgecolors='white', s=50)
    mn = min(Y_test[:, i].min(), Y_pred_ensemble[:, i].min())
    mx = max(Y_test[:, i].max(), Y_pred_ensemble[:, i].max())
    ax.plot([mn, mx], [mn, mx], 'r--', lw=1.5, label='Perfect fit')
    ax.set_xlabel('Actual')
    ax.set_ylabel('Predicted')
    ax.set_title(f'{target}\nR²={ensemble_r2[i]:.3f}', fontsize=9)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)

plt.tight_layout()
plt.savefig('/mnt/data/06_actual_vs_predicted.png', dpi=150, bbox_inches='tight')
plt.close()
print("  Saved: 06_actual_vs_predicted.png")

print("\n" + "=" * 60)
print("PIPELINE COMPLETE")
print("=" * 60)
print("""
Key Library Summary:
  DOE:            pyDOE2 (lhs), scipy.stats.qmc (LatinHypercube)
  Data:           pandas, numpy
  Imputation:     sklearn.impute.KNNImputer, SimpleImputer
  Preprocessing:  sklearn.preprocessing.StandardScaler
  Multi-Output:   sklearn.multioutput.MultiOutputRegressor
                  sklearn.multioutput.RegressorChain
  Models:         sklearn (Ridge/Lasso/RF/ET/GB/DT), lightgbm, xgboost
  Metrics:        sklearn.metrics (r2_score, mean_squared_error, mean_absolute_error)
  Explainability: shap (TreeExplainer)
  Visualization:  matplotlib, seaborn
""")
