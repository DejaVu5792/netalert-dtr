#!/bin/bash

# NetAlertX DTR YAML Batch Processor
set -e

# 1. Check if yq is installed
if ! command -v yq &> /dev/null; then
    echo "Error: 'yq' is not installed. Please install it to process YAML files."
    exit 1
fi

# 2. Load environment variables
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
else
    echo "Error: .env file not found"
    exit 1
fi

# 3. Check required environment variables
if [ -z "$NETALERTX_HOST" ] || [ -z "$NETALERTX_TOKEN" ]; then
    echo "Error: NETALERTX_HOST and NETALERTX_TOKEN must be set in .env"
    exit 1
fi

# 4. Script configuration
YAML_FILE="${1:-batch.yaml}"
OUTPUT_DIR="${2:-output}"

if [ ! -f "$YAML_FILE" ]; then
    echo "Error: YAML file '$YAML_FILE' not found"
    echo "Usage: $0 [config.yaml] [output_dir]"
    exit 1
fi

mkdir -p "$OUTPUT_DIR"

echo "Processing configuration: $YAML_FILE"
echo "------------------------------------------"

# 5. Process each job in the YAML 'jobs' list
# Updated: Added .consolidate to the array and used // "" to handle missing fields
yq e '.jobs[] | [.type, .name, .start_date // "_NONE_", .end_date // "_NONE_", .output_name // "_NONE_", .consolidate // "false"] | @tsv' "$YAML_FILE" | while IFS=$'\t' read -r type name start_date end_date output_name consolidate; do

    # Skip if type is empty
    [[ -z "$type" || "$type" == "null" ]] && continue

    echo "Target: $name ($type)"

    # Build the command dynamically based on provided fields
    case "$type" in
        device|owner|group)
            cmd="uv run dtr_generator.py --$type \"$name\""
            ;;
        *)
            echo "  [!] Warning: Unknown type '$type', skipping..."
            continue
            ;;
    esac

    # Add optional arguments if they aren't empty/null
    [[ -n "$start_date" && "$start_date" != "_NONE_" && "$start_date" != "null" ]] && cmd="$cmd --start-date \"$start_date\""
    [[ -n "$end_date" && "$end_date" != "_NONE_" && "$end_date" != "null" ]]       && cmd="$cmd --end-date \"$end_date\""
    [[ "$consolidate" == "true" ]] && cmd="$cmd --consolidate"

    # Add output path if provided
    if [[ -n "$output_name" && "$output_name" != "_NONE_" && "$output_name" != "null" ]]; then
        cmd="$cmd --output \"$OUTPUT_DIR/$output_name.csv\""
    fi

    # Execute
    if eval "$cmd"; then
        echo "  [✓] Success"
    else
        echo "  [✗] Error processing '$name'"
    fi
    echo "------------------------------------------"

done

echo "Batch processing complete!"
