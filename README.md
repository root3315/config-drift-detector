# Config Drift Detector

Ever had your app behave weirdly because some env var wasn't set, or a config value drifted from what you expected? Yeah, me too. This tool helps catch that.

## What it does

Takes your declared config (JSON or YAML) and compares it against actual runtime state. Tells you what's missing, what's extra, and what doesn't match.

## Quick start

```bash
# Install deps (if using YAML)
pip install -r requirements.txt

# Run it
python config_drift_detector.py my-config.yaml
```

## Example config file

Create a `expected-config.yaml`:

```yaml
env:
  APP_ENV: production
  LOG_LEVEL: info
  DATABASE_URL: postgres://localhost/mydb
runtime:
  python_version: "3.11"
  platform: linux
```

Then run:

```bash
python config_drift_detector.py expected-config.yaml
```

You'll get a report showing what matches and what's drifted.

## Runtime sources

The tool can check against different runtime state sources:

- `env` - All environment variables (default)
- `cwd` - Current working directory (default)
- `python_version` - Python version
- `platform` - OS platform
- `file:<path>` - Content of a file
- `env_file:<path>` - Parse a .env file

Add multiple with `-r`:

```bash
python config_drift_detector.py config.yaml \
  -r env \
  -r python_version \
  -r platform
```

## Ignoring stuff

Some things you just don't care about. Ignore them:

```bash
python config_drift_detector.py config.yaml \
  -i env.LC_ \
  -i env.PWD
```

## Output options

Verbose mode (shows matched keys too):

```bash
python config_drift_detector.py config.yaml -v
```

Export results to JSON:

```bash
python config_drift_detector.py config.yaml -o drift-results.json
```

Use in CI (exit code 1 if drift detected):

```bash
python config_drift_detector.py config.yaml --exit-code
```

## Why I built this

Honestly, I kept debugging issues where someone changed an env var in production but forgot to update the docs. Or a deployment script set something different than what the config said. This lets me codify what "correct" looks like and check against it.

## Limitations

- Doesn't do deep type checking (string "3.11" vs number 3.11 will mismatch)
- YAML support needs pyyaml installed
- Only handles flat or nested dict configs (no arrays at root level)

## License

Do whatever you want with it.
