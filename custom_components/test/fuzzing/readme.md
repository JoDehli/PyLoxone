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
## Random testing 
> - not needed for grade bonus
- [ ] Implement a `RandomFuzzer`.
  - The return value should be identical to the `fuzz()` function of the `ValuePoolFuzzer` class so that the `ParamRunner` can be used.
  - assigend to: ---

## Value pools
- [ ] Update `fuzz()` function in `ValuePoolFuzzer` class. 
  - [x] so that 2-way, 3-way, ... pools can be created
  - [ ] Update UML if needed
  - [ ] Implement and test on at least one test case in `test_vp_on_helpers.py`
  - [x] Create merge request 
  - assigend to: @jonathanheitzmann
  - @jonathanheitzmann works on branch `param_combi`
- [ ] Create `limit_param_set(param_set : set, runs : int)` function in `ValuePoolFuzzer` class. 
  - [ ] Function takes a generated `param_set` (list of lists) and the integer `runs`. If `runs` is lower than the number of Lists in the `param_set` randomly sets are picked, so that `runs` is equal to number of lists in `param_set`.
  - [ ] Update UML if needed
  - [ ] Implement and test on at least one test case in `test_vp_on_helpers.py`
  - [ ] Create merge request 
  - assigend to: @hoegma
  - @hoegma works on branch `fuzzing/value_pools-limit_param`
- [ ] The parameter `param_nr` is superfluous and is not required in the function `fuzz()` of the `ValuePoolFuzzer` class. The number of parameters is already determined by the length of list `types`.
  - assigend to: ---
- [ ] The value pools contain no no neutral element like `None` or `NaN`. 
  - assigend to: ---
- [ ] To avoid duplication in the code, value pools should "inherit" from each other in some way.  For example, "INT" also takes all values from "UINT" (identical to Balista).
  - assigend to: ---

## Generators
- [ ] Implement the generators.
  - [ ] present concept
  - [ ] Update UML if needed
  - [ ] Are there any subtasks that can be given to someone else?
  - [ ] Create merge request 
  - assigend to: @dsiev
  - @dsiev works on branch `fuzzing/generators`

## Input grammars
- [ ] Implement the grammars.
  - [ ] present concept
  - [ ] Update UML if needed
  - [ ] Are there any subtasks that can be given to someone else?
  - [ ] Create merge request 
  - assigend to: @JKortmann
  - @JKortmann works on branch `fuzzing/grammars`

## Mutational 
### black-box
- [ ] Implement the mutational fuzzing (black-box).
  - [ ] present concept
  - [ ] Update UML if needed
  - [ ] Create merge request 
  - assigend to: @ThorbenCarl
  - @ThorbenCarl works on branch `fuzzing/mutational_black_box`
### grey-box
- [ ] Implement the mutational fuzzing (grey-box).
  - [ ] present concept
  - [ ] Update UML if needed
  - [ ] Create merge request 
  - assigend to: @hoegma
  - @hoegma works on branch `fuzzing/mutational_grey_box`

## Search based

# Vulnerabilities found
## `helpers.py`
### `map_range()`
- A possible 0 division is not checked or intercepted.