#!/usr/bin/env python3
"""
Config Drift Detector - Detects drift between declared config and runtime state.
"""

import json
import os
import sys
import argparse
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False


def load_config_file(filepath: str) -> Dict[str, Any]:
    """Load configuration from JSON or YAML file."""
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {filepath}")
    
    content = path.read_text()
    
    if path.suffix in ['.yaml', '.yml']:
        if not YAML_AVAILABLE:
            raise ImportError("PyYAML not installed. Install with: pip install pyyaml")
        return yaml.safe_load(content) or {}
    elif path.suffix == '.json':
        return json.loads(content)
    else:
        raise ValueError(f"Unsupported config format: {path.suffix}")


def flatten_dict(d: Dict[str, Any], parent_key: str = '', sep: str = '.') -> Dict[str, Any]:
    """Flatten nested dictionary into dot-notation keys."""
    items = []
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.extend(flatten_dict(v, new_key, sep).items())
        else:
            items.append((new_key, v))
    return dict(items)


def get_runtime_state(sources: List[str]) -> Dict[str, Any]:
    """Collect runtime state from various sources."""
    state = {}
    
    for source in sources:
        if source == 'env':
            for key, value in os.environ.items():
                state[f'env.{key}'] = value
        elif source == 'cwd':
            state['runtime.cwd'] = os.getcwd()
        elif source == 'python_version':
            state['runtime.python_version'] = sys.version.split()[0]
        elif source == 'platform':
            state['runtime.platform'] = sys.platform
        elif source.startswith('file:'):
            filepath = source[5:]
            if os.path.exists(filepath):
                state[f'file.{filepath}'] = Path(filepath).read_text()
            else:
                state[f'file.{filepath}'] = None
        elif source.startswith('env_file:'):
            filepath = source[9:]
            if os.path.exists(filepath):
                for line in Path(filepath).read_text().splitlines():
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, _, value = line.partition('=')
                        state[f'env_file.{filepath}.{key.strip()}'] = value.strip().strip('"\'')
    
    return state


def compare_configs(declared: Dict[str, Any], actual: Dict[str, Any], 
                    ignore_keys: Optional[List[str]] = None) -> Dict[str, Any]:
    """Compare declared config against actual runtime state."""
    ignore_keys = ignore_keys or []
    
    declared_flat = flatten_dict(declared)
    actual_flat = flatten_dict(actual)
    
    drift = {
        'missing': {},
        'extra': {},
        'mismatched': {},
        'matched': {}
    }
    
    all_keys = set(declared_flat.keys()) | set(actual_flat.keys())
    
    for key in all_keys:
        if any(key.startswith(ignore) for ignore in ignore_keys):
            continue
        
        declared_val = declared_flat.get(key)
        actual_val = actual_flat.get(key)
        
        if key not in actual_flat:
            drift['missing'][key] = declared_val
        elif key not in declared_flat:
            drift['extra'][key] = actual_val
        elif declared_val != actual_val:
            drift['mismatched'][key] = {
                'declared': declared_val,
                'actual': actual_val
            }
        else:
            drift['matched'][key] = declared_val
    
    return drift


def format_drift_report(drift: Dict[str, Any], verbose: bool = False) -> str:
    """Format drift results as human-readable report."""
    lines = []
    lines.append("=" * 60)
    lines.append("CONFIG DRIFT DETECTION REPORT")
    lines.append(f"Generated: {datetime.now().isoformat()}")
    lines.append("=" * 60)
    
    missing_count = len(drift['missing'])
    extra_count = len(drift['extra'])
    mismatched_count = len(drift['mismatched'])
    matched_count = len(drift['matched'])
    
    lines.append("")
    lines.append("SUMMARY")
    lines.append("-" * 40)
    lines.append(f"  Matched:     {matched_count}")
    lines.append(f"  Missing:     {missing_count}")
    lines.append(f"  Extra:       {extra_count}")
    lines.append(f"  Mismatched:  {mismatched_count}")
    
    total_drift = missing_count + extra_count + mismatched_count
    if total_drift == 0:
        lines.append("")
        lines.append("STATUS: ✓ No drift detected")
    else:
        lines.append("")
        lines.append(f"STATUS: ✗ Drift detected ({total_drift} issues)")
    
    if drift['missing']:
        lines.append("")
        lines.append("MISSING (declared but not in runtime)")
        lines.append("-" * 40)
        for key, value in sorted(drift['missing'].items()):
            lines.append(f"  - {key}: {value}")
    
    if drift['extra']:
        lines.append("")
        lines.append("EXTRA (in runtime but not declared)")
        lines.append("-" * 40)
        for key, value in sorted(drift['extra'].items()):
            lines.append(f"  + {key}: {value}")
    
    if drift['mismatched']:
        lines.append("")
        lines.append("MISMATCHED (values differ)")
        lines.append("-" * 40)
        for key, values in sorted(drift['mismatched'].items()):
            lines.append(f"  ~ {key}:")
            lines.append(f"      declared: {values['declared']}")
            lines.append(f"      actual:   {values['actual']}")
    
    if verbose and drift['matched']:
        lines.append("")
        lines.append("MATCHED")
        lines.append("-" * 40)
        for key, value in sorted(drift['matched'].items()):
            lines.append(f"  ✓ {key}: {value}")
    
    lines.append("")
    lines.append("=" * 60)
    
    return "\n".join(lines)


def export_drift_json(drift: Dict[str, Any], output_path: str) -> None:
    """Export drift results to JSON file."""
    output = {
        'timestamp': datetime.now().isoformat(),
        'drift': drift
    }
    Path(output_path).write_text(json.dumps(output, indent=2))


def main():
    parser = argparse.ArgumentParser(
        description='Detect drift between declared config and runtime state'
    )
    parser.add_argument(
        'config_file',
        help='Path to declared config file (JSON or YAML)'
    )
    parser.add_argument(
        '--runtime-source', '-r',
        action='append',
        default=['env', 'cwd'],
        help='Runtime state sources: env, cwd, python_version, platform, file:<path>, env_file:<path>'
    )
    parser.add_argument(
        '--ignore', '-i',
        action='append',
        default=[],
        help='Key prefixes to ignore (e.g., "env.LC_")'
    )
    parser.add_argument(
        '--output', '-o',
        help='Output JSON file for drift results'
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Show matched keys in report'
    )
    parser.add_argument(
        '--exit-code',
        action='store_true',
        help='Exit with code 1 if drift detected'
    )
    
    args = parser.parse_args()
    
    try:
        declared = load_config_file(args.config_file)
    except (FileNotFoundError, ValueError, ImportError) as e:
        print(f"Error loading config: {e}", file=sys.stderr)
        sys.exit(1)
    
    actual = get_runtime_state(args.runtime_source)
    drift = compare_configs(declared, actual, args.ignore)
    
    report = format_drift_report(drift, args.verbose)
    print(report)
    
    if args.output:
        export_drift_json(drift, args.output)
        print(f"\nDrift results exported to: {args.output}")
    
    if args.exit_code:
        has_drift = (len(drift['missing']) + 
                     len(drift['extra']) + 
                     len(drift['mismatched'])) > 0
        sys.exit(1 if has_drift else 0)


if __name__ == '__main__':
    main()
