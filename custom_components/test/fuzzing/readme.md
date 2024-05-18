# Fuzzing
## What is Fuzzing
Fuzzing, or fuzz testing, is a software testing technique used to find vulnerabilities and bugs by inputting large amounts of random data, called "fuzz," into a program. 
The goal is to induce unexpected behavior, crashes, or memory leaks, thereby revealing security issues and flaws that might not be detected through traditional testing methods. 
By systematically feeding malformed or semi-random data to the software, fuzzing helps developers identify and fix critical vulnerabilities, enhancing the overall robustness and security of the application.

## Why are we fuzzing?
We are 5 students, and we have to fuzz an open source project for a grade bonus. 
So here we are!

## Start to fuzz
### Setup
- install the following packages:
```shell
pip install pytest
pip install pytest-timeout
pip install homeassistant
```
- you maybe have to tell python were to find the `PyLoxone` project 
```shell
export PYTHONPATH=$PYTHONPATH:/path/to/PyLoxone
```
### Run
- start the execution in the root of the repo
```shell
cd /path/to/PyLoxone
```
- run `pytest`
```shell
pytest
```

## Fuzzer layout (UML)
![fuzzer_overview](fuzzer_overview.svg)

# TODO
- @ThorbenCarl: add .venv setup
- add test files
- consider imports
## Random testing 

## Value pools
- @jonathanheitzmann: custom_components/test/fuzzing/fuzzer_utils/ValuePool.py
- @jonathanheitzmann: custom_components/test/fuzzing/fuzzer_utils/ValuePoolFuzzer.py
- @hoegma: custom_components/test/fuzzing/fuzzer_utils/ParamRunner.py

- create test case with different value pools for one function
- write function that creates 2-way, 3-way, ... pools
- fuzz more funktions
- timeout?

## Generators
- @JKortmann: custom_components/test/fuzzing/fuzzer_utils/GeneratorRunner.py

## Input grammars

## Mutational 
### black-box
### grey-box

## Search based

# Vulnerabilities found
## `helpers.py`
### `map_range`
- possible zero division
