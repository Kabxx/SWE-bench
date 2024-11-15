#!/usr/bin/env bash

python -m swebench.inference.run_api\
 --dataset_name_or_path r1v3r/SWE-bench_bitflags_style-3__fs-oracle\
 --model_name_or_path gpt-4o-2024-08-06 --output_dir ./outputs\
 --split train\
 --instance_ids bitflags__bitflags-266
