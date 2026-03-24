#!/usr/bin/env python3
"""
Config Drift Detector - Detects drift between declared config and runtime state.
"""

import json
import os
import sys
import argparse
import re
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, Union

try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False


def normalize_type(value: Any) -> Tuple[Any, str]:
    """
    Normalize a value to its canonical type and return (normalized_value, type_name).
    Handles string representations of common types.
    """
    if value is None:
        return None, 'null'
    
    if isinstance(value, bool):
        return value, 'boolean'
    
    if isinstance(value, int):
        return value, 'integer'
    
    if isinstance(value, float):
        return value, 'float'
    
    if isinstance(value, str):
        if value.lower() in ('true', 'false'):
            return value.lower() == 'true', 'boolean'
        
        if value.lower() in ('null', 'none', '~', ''):
            return None, 'null'
        
        int_pattern = r'^-?\d+$'
        if re.match(int_pattern, value):
            try:
                return int(value), 'integer'
            except ValueError:
                pass
        
        float_pattern = r'^-?\d+\.\d+$'
        if re.match(float_pattern, value):
            try:
                return float(value), 'float'
            except ValueError:
                pass
        
        return value, 'string'
    
    if isinstance(value, list):
        return value, 'array'
    
    if isinstance(value, dict):
        return value, 'object'
    
    return value, type(value).__name__


def types_compatible(declared: Any, actual: Any, strict: bool = False) -> Tuple[bool, str]:
    """
    Check if two values are type-compatible.
    
    Returns (is_compatible, reason).
    
    In non-strict mode, allows numeric coercion between int/float/string.
    In strict mode, requires exact type match.
    """
    declared_norm, declared_type = normalize_type(declared)
    actual_norm, actual_type = normalize_type(actual)
    
    if declared_type == actual_type:
        return True, 'exact_type_match'
    
    numeric_types = {'integer', 'float'}
    
    if declared_type in numeric_types and actual_type in numeric_types:
        if declared_norm == actual_norm:
            return True, 'numeric_coercion'
        return False, f'numeric_mismatch:{declared_norm}!={actual_norm}'
    
    if declared_type == 'string' and actual_type in numeric_types:
        declared_as_num, _ = normalize_type(str(declared_norm))
        if declared_as_num is not None and declared_as_num == actual_norm:
            return True, 'string_numeric_coercion'
    
    if actual_type == 'string' and declared_type in numeric_types:
        actual_as_num, _ = normalize_type(str(actual_norm))
        if actual_as_num is not None and actual_as_num == declared_norm:
            return True, 'string_numeric_coercion'
    
    return False, f'type_mismatch:{declared_type}!={actual_type}'


def deep_compare(declared: Any, actual: Any, strict_types: bool = False) -> Dict[str, Any]:
    """
    Deep comparison with type awareness.
    
    Returns dict with:
        - match: bool
        - reason: str explaining the comparison result
        - declared_normalized: normalized declared value
        - actual_normalized: normalized actual value
    """
    declared_norm, declared_type = normalize_type(declared)
    actual_norm, actual_type = normalize_type(actual)
    
    if declared_type == 'object' and actual_type == 'object':
        if set(declared_norm.keys()) != set(actual_norm.keys()):
            return {
                'match': False,
                'reason': 'different_keys',
                'declared_normalized': declared_norm,
                'actual_normalized': actual_norm
            }
        for key in declared_norm:
            key_result = deep_compare(declared_norm[key], actual_norm[key], strict_types)
            if not key_result['match']:
                return {
                    'match': False,
                    'reason': f'key_{key}_mismatch:{key_result["reason"]}',
                    'declared_normalized': declared_norm,
                    'actual_normalized': actual_norm
                }
        return {
            'match': True,
            'reason': 'deep_object_match',
            'declared_normalized': declared_norm,
            'actual_normalized': actual_norm
        }
    
    if declared_type == 'array' and actual_type == 'array':
        if len(declared_norm) != len(actual_norm):
            return {
                'match': False,
                'reason': f'array_length_mismatch:{len(declared_norm)}!={len(actual_norm)}',
                'declared_normalized': declared_norm,
                'actual_normalized': actual_norm
            }
        for i, (d_item, a_item) in enumerate(zip(declared_norm, actual_norm)):
            item_result = deep_compare(d_item, a_item, strict_types)
            if not item_result['match']:
                return {
                    'match': False,
                    'reason': f'array_index_{i}_mismatch:{item_result["reason"]}',
                    'declared_normalized': declared_norm,
                    'actual_normalized': actual_norm
                }
        return {
            'match': True,
            'reason': 'deep_array_match',
            'declared_normalized': declared_norm,
            'actual_normalized': actual_norm
        }
    
    is_compat, reason = types_compatible(declared, actual, strict_types)
    if is_compat:
        return {
            'match': True,
            'reason': reason,
            'declared_normalized': declared_norm,
            'actual_normalized': actual_norm
        }
    
    return {
        'match': False,
        'reason': reason,
        'declared_normalized': declared_norm,
        'actual_normalized': actual_norm
    }


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
                    ignore_keys: Optional[List[str]] = None,
                    strict_types: bool = False,
                    deep_check: bool = True) -> Dict[str, Any]:
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
        elif deep_check:
            comparison = deep_compare(declared_val, actual_val, strict_types)
            if comparison['match']:
                drift['matched'][key] = {
                    'declared': declared_val,
                    'actual': actual_val,
                    'normalization': comparison['reason']
                }
            else:
                drift['mismatched'][key] = {
                    'declared': declared_val,
                    'actual': actual_val,
                    'declared_normalized': comparison['declared_normalized'],
                    'actual_normalized': comparison['actual_normalized'],
                    'reason': comparison['reason']
                }
        else:
            if declared_val != actual_val:
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
            if 'reason' in values:
                lines.append(f"      reason:   {values['reason']}")
            if 'declared_normalized' in values:
                lines.append(f"      declared_normalized: {values['declared_normalized']}")
                lines.append(f"      actual_normalized:   {values['actual_normalized']}")

    if verbose and drift['matched']:
        lines.append("")
        lines.append("MATCHED")
        lines.append("-" * 40)
        for key, value in sorted(drift['matched'].items()):
            if isinstance(value, dict):
                lines.append(f"  ✓ {key}: {value['declared']} (normalized: {value.get('normalization', 'N/A')})")
            else:
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
    parser.add_argument(
        '--strict-types',
        action='store_true',
        help='Require exact type matches (no numeric coercion)'
    )
    parser.add_argument(
        '--no-deep-check',
        action='store_true',
        help='Disable deep type checking (use simple equality)'
    )

    args = parser.parse_args()

    try:
        declared = load_config_file(args.config_file)
    except (FileNotFoundError, ValueError, ImportError) as e:
        print(f"Error loading config: {e}", file=sys.stderr)
        sys.exit(1)

    actual = get_runtime_state(args.runtime_source)
    drift = compare_configs(
        declared, 
        actual, 
        args.ignore,
        strict_types=args.strict_types,
        deep_check=not args.no_deep_check
    )

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
