#!/bin/sh

# Define a space-separated list of folder paths
folders="custom_components/loxone \
custom_components/loxone/pyloxone_api \
custom_components/loxone/pyloxone_api/tests"

# Loop through each folder and run black and isort
for folder in $folders
do
    black "$folder"
    isort "$folder"
done