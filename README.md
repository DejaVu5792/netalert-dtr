# NetAlertX Daily Time Record Generator

Generate daily time records from [NetAlertX](https://github.com/netalertx/NetAlertX) session data.

## Quickstart

### Install

```bash
uv sync
```

### Configure

Copy the example environment file and add your credentials:

```bash
cp .env.example .env
```

Edit `.env`:

```env
NETALERTX_HOST=http://host:GRAPHQL_PORT
NETALERTX_TOKEN=API_TOKEN
```

### Generate DTR

Generate for a specific device:

```bash
uv run dtr_generator.py --device "iPhone X"
```

Generate for all devices owned by a person (consolidates):

```bash
uv run dtr_generator.py --owner "John Doe" --start-date "2026-01-01" --end-date "2026-01-31"
```

Generate for multiple devices with same prefix:

```bash
uv run dtr_generator.py --device "iPhone" --consolidate --output "all_iphones.csv"
```

### Batch Processing

Process multiple jobs from a YAML configuration file:

```bash
./batch_process.sh [config.yaml] [output_dir]
```

Requires `yq` to be installed. Creates a YAML file with jobs:

```yaml
jobs:
  - name: "iPhone X"
    type: device

  - name: "John Doe"
    type: owner
    start_date: 2026-01-01
    end_date: 2026-01-31
    output_name: doe_january
```

## Options

- `--device` - Filter by device name (partial match)
- `--owner` - Filter by owner (consolidates all matching devices)
- `--group` - Filter by group (consolidates all matching devices)
- `--start-date` - Start date (YYYY-MM-DD, default: 30 days ago)
- `--end-date` - End date (YYYY-MM-DD, default: today)
- `--output, -o` - Output CSV path (default: auto-generated)
- `--consolidate` - Consolidate multiple device matches
- `--host` - NetAlertX host (overrides .env)
- `--token` - API token (overrides .env)

## Output Format

```csv
date,time_in,time_out
2026-01-19,12:42:41,17:01:13
2026-01-20,08:30:00,17:45:22
```

- `date` - Date (YYYY-MM-DD)
- `time_in` - First connection time (HH:MM:SS)
- `time_out` - Last disconnection time (HH:MM:SS)

Days with no sessions are omitted. Blank `time_out` means device still connected.

## Credits & Disclosures

### Dependencies
- [NetAlertX](https://github.com/netalertx/NetAlertX) - The powerful network security scanner providing the data.
- [yq](https://github.com/mikefarah/yq) - Used for parsing YAML in the batch processor.

### AI Disclosure

This project was developed with assistance from AI models including GLM-4.7 (via [OpenCode](https://opencode.ai/)) and Google Gemini.

### License
This project is licensed under the [MIT License](LICENSE).
