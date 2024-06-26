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
1. create a virtual environment:

You can create the virtual environment in the project's root directory (recommended) or any other directory of your choice.
```shell
python -m venv venv
```
2. activate the virtual environment:

Windows
```shell
.\venv\Scripts\activate
```

Linux and macOS
```shell
source venv/bin/activate
```

3.  install the following packages:
```shell
pip install pytest
pip install pytest-timeout
pip install homeassistant
pip install numpy
```
4. you maybe have to tell python were to find the `PyLoxone` project 

Windows
- Go to the Windows menu and search for "Environment Variables".
- Select “Advanced system settings”.
- In the “System Properties” window, click the “Environment Variables” button.
- Click the “New” button in the top half of the dialog, to make a new user variable.
- Name the variable PYTHONPATH and set its value to the path of your code directory. Click "OK" and "OK" again to save.

Linux and macOS
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
- if you only want to run a single test file, you can enter the path to the file:
```shell
pytest custom_components/test/path/to/test_file.py
```

## Fuzzer layout (UML)
![fuzzer_overview](fuzzer_overview.svg)

# TODO
## Presentation 2024-07-05
1. @jonathanheitzmann presenting
  - value pools: 
    - `ValuePool` 
    - `ValuePoolFuzzer` 
  - corresponding test cases.
2. @dsiev presenting
  - generators 
    - `fuzzer` 
    - `runner` ?
  - corresponding test cases.
3. @JKortmann presenting
  - grammars 
    - `GrammerFuzzer`
    - `grammar_pool`
  - corresponding test cases.
4. @ThorbenCarl presenting
  - black box mutational 
    - `MutationalFuzzer`
  - corresponding test cases.
5. @hoegma presenting
  - grey box mutational 
    - ?
  - corresponding test cases.

## Random testing 
> - Assigned to:
> - Branch: `fuzzing/random_testing`
- [ ] Implement a `RandomFuzzer`.
  - The return value should be identical to the `fuzz()` function of the `ValuePoolFuzzer` class so that the `ParamRunner` can be used.

## Value pools 
> - Assigned to: @jonathanheitzmann
> - Branch: `fuzzing/valuepool`

## Generators
> - Assigned to: @dsiev
> - Branch: `fuzzing/generators`
- Implement the generators.
  - [ ] Get code running
  - [ ] Update UML
  - [ ] Create test cases

## Input grammars
> - Assigned to: @JKortmann
- Implement the grammars.
  - [ ] (OPTIONAL) test cases for: `test_get_room_name_from_room_uuid()`, `test_get_cat_name_from_cat_uuid()` and `test_add_room_and_cat_to_value_values()` from `helper.py`
  - [ ] (OPTIONAL) Implementation of three-phase derivation (or random for the `MutationalFuzzer`)
  - [ ] (OPTIONAL) Implementation of probabilistic derivation

## Mutational 
### black-box
> - Assigned to: @ThorbenCarl
> - Branch: `fuzzing/mutational_black_box`

### grey-box
> - Assigned to: @hoegma
> - Branch: `fuzzing/mutational_grey_box`
- [ ] Implement the mutational fuzzing (grey-box).
  - [ ] Present concept
  - [ ] Update UML

### white-box
> - Assigned to: --
> - Branch: `fuzzing/mutational_white_box`

## Search based
> - Assigned to:
> - Branch: `fuzzing/search_based`

# Vulnerabilities found
## `helpers.py`
### `map_range()`
- A possible 0 division is not checked or intercepted.

### `get_all()`
- If the key `controls` or `type` is not in the `json_data: dict` the function crashes.