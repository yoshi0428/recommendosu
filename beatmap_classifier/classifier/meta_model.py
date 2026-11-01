"""
The XGBoost meta-model's inputs and training helpers, shared by
train_full.ipynb and train_and_eval.ipynb.

The meta-model sees each map's 5 CNN probabilities followed by its
additional features (stats + movement features, ADDITIONAL_FEATURE_NAMES),
or a subset of them picked by index.
"""

import numpy as np
import optuna
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from xgboost import XGBClassifier

from beatmap_classifier.classifier.augment_faster import extract_movement_features_from_X
from beatmap_classifier.classifier.inference import (  # noqa: F401 (re-exported for the notebooks)
    ADDITIONAL_FEATURE_NAMES,
    MOVEMENT_FEATURE_NAMES,
    SQL_FEATURE_NAMES,
)
from beatmap_classifier.classifier.utils_training import TOURNAMENT_MODS

CNN_FEATURE_NAMES = ["CNN_NM1", "CNN_NM2", "CNN_NM3", "CNN_NM4", "CNN_NM5"]


def additional_features(X_padded, raw_additional_features, beatmap_ids, y):
    """
    [maps, 24] float32 array of ADDITIONAL_FEATURE_NAMES: each map's stats
    (from get_additional_features(), on the variant its label is played
    with), then the movement features of its padded and cut vectors.
    """
    sql_features = np.array(
        [raw_additional_features[(beatmap_id, TOURNAMENT_MODS.get(label, "NM"))] for beatmap_id, label in zip(beatmap_ids, y)],
        dtype=np.float32,
    )
    movement_features = np.array(
        [extract_movement_features_from_X(X_padded[i]) for i in range(len(X_padded))],
        dtype=np.float32,
    )
    return np.hstack([sql_features, movement_features])


def get_feature_indices(feature_names, selected_features):
    missing = [name for name in selected_features if name not in feature_names]

    if missing:
        raise ValueError(f"Features not found: {missing}")

    return [feature_names.index(name) for name in selected_features]


def meta_features(cnn_predictions, X_additional, indices):
    """The meta-model's input: CNN probabilities, then the selected additional features."""
    return np.hstack([cnn_predictions, X_additional[:, indices]])


def make_xgb(params):
    return XGBClassifier(
        random_state=42,
        objective="multi:softprob",
        num_class=5,
        eval_metric="mlogloss",
        **params,
    )


def optimize_xgb_feature_set(X_additional, oof_cnn_predictions, y, indices, n_trials=50, seed=42):
    """Optuna search for the XGBoost params with the best 5-fold CV macro F1."""
    X_meta = meta_features(oof_cnn_predictions, X_additional, indices)
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=seed)

    def objective(trial):
        params = {
            "n_estimators": trial.suggest_int("n_estimators", 250, 750, step=50),
            "learning_rate": trial.suggest_float("learning_rate", 0.005, 0.1, log=True),
            "max_depth": trial.suggest_int("max_depth", 2, 8),
            "min_child_weight": trial.suggest_int("min_child_weight", 1, 10),
            "subsample": trial.suggest_float("subsample", 0.6, 1.0),
            "colsample_bytree": trial.suggest_float("colsample_bytree", 0.6, 1.0),
            "reg_alpha": trial.suggest_float("reg_alpha", 1e-4, 1.0, log=True),
            "reg_lambda": trial.suggest_float("reg_lambda", 0.1, 10.0, log=True),
        }

        scores = []

        for train_idx, valid_idx in cv.split(X_meta, y):
            model = make_xgb(params)
            model.fit(X_meta[train_idx], y[train_idx], eval_set=[(X_meta[valid_idx], y[valid_idx])], verbose=False)
            pred = model.predict(X_meta[valid_idx])
            scores.append(f1_score(y[valid_idx], pred, average="macro", zero_division=0))

        return np.mean(scores)

    study = optuna.create_study(direction="maximize", sampler=optuna.samplers.TPESampler(seed=seed))
    study.optimize(objective, n_trials=n_trials, show_progress_bar=True)
    return study


def cv_evaluate_feature_set(indices, X_additional, oof_cnn_predictions, y, params, seed=42):
    """
    Score a feature set with 5-fold CV (on the train split in
    train_and_eval.ipynb, so feature selection never sees the test set).
    """
    X_meta = meta_features(oof_cnn_predictions, X_additional, indices)
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=seed)
    pred = cross_val_predict(make_xgb(params), X_meta, y, cv=cv)
    cm = confusion_matrix(y, pred)

    return {
        "accuracy": accuracy_score(y, pred),
        "macro_f1": f1_score(y, pred, average="macro"),
        "nm3_to_nm4": cm[2, 3],
        "nm4_to_nm3": cm[3, 2],
    }


def fit_meta_model(indices, X_additional, oof_cnn_predictions, y, params):
    model = make_xgb(params)
    model.fit(meta_features(oof_cnn_predictions, X_additional, indices), y)
    return model
