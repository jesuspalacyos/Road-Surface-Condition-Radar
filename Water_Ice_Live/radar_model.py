"""Experimental dry/wet/ice reference sample matching (not a validated ice detector)."""
import json
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent
LABELS = ['dry', 'water/wet', 'ice']
CODES = {'unknown': -1, 'dry': 0, 'water/wet': 1, 'ice': 2}


def load_model():
    obj = json.loads((ROOT / 'data/surface_samples.json').read_text(encoding='utf-8'))
    groups = [np.asarray([w for s in obj['sessions'] if s['label'] == label
                          for w in s['windows']], float)
              for label in ['dry', 'wet', 'ice']]
    centers = np.array([np.median(g, axis=0) for g in groups])
    scale = np.maximum(centers.std(axis=0), 32)
    radii = np.array([max(.35, 1.5 * np.quantile(np.sqrt(np.mean(((g - c) / scale)**2, axis=1)), .95))
                      for g, c in zip(groups, centers)])
    return obj['metadata'], groups, centers, scale, radii


def classify(x, model):
    _, _, centers, scale, radii = model
    distances = np.sqrt(np.mean(((centers - x) / scale)**2, axis=1))
    order = np.argsort(distances)
    k, second = order[:2]
    margin = (distances[second] - distances[k]) / max(distances[second], 1e-9)
    label = LABELS[k] if distances[k] <= radii[k] and margin >= .25 else 'unknown'
    return label, float(margin), distances


def plot(fig, rows, count, mode):
    fig.clear()
    axes = fig.subplots(3, 1, sharex=True)
    data = rows[:count]
    times = [r['time_s'] for r in data]
    colors = ['#bf7e27', '#008bc2', '#7047bd']
    for k, c in zip(['dry', 'wet', 'ice'], colors):
        axes[0].plot(times, [r['distance_' + k] for r in data], label=k, color=c, lw=1.5)
    axes[0].set_ylabel('Match distance\n(lower is closer)')
    axes[0].legend(loc='upper right', ncol=3)
    for b in [3, 4, 5, 6]:
        axes[1].plot(times, [r[f'bin_{b:03d}'] for r in data], label=f'Bin {b}', lw=1)
    axes[1].set_ylabel('Raw profile counts')
    axes[1].legend(loc='upper right', ncol=4)
    axes[2].step(times, [CODES[r['predicted_surface']] for r in data], where='post', color='#086b56', label='Prediction')
    if mode == 'demo':
        axes[2].step(times, [CODES[r['scenario_label']] for r in data], where='post', ls='--', color='#a46919', alpha=.7, label='Synthetic scenario')
    axes[2].set_yticks([-1, 0, 1, 2], ['Unknown', 'Dry', 'Water / wet', 'Ice'])
    axes[2].set_ylim(-1.4, 2.5)
    axes[2].set_xlabel('Elapsed time (seconds)')
    axes[2].legend(loc='upper right', ncol=2)
    for ax in axes:
        ax.grid(alpha=.18)
        ax.set_xlim(0, max(rows[-1]['time_s'], 1))
    fig.suptitle('LIVE radar — ground truth unknown\nExperimental sample matching • scores are not probabilities', fontsize=13)
    fig.subplots_adjust(top=.87, bottom=.17, left=.13, right=.97, hspace=.22)
