from ValuePoolFuzzer import ValuePoolFuzzer

def main():
    # Erstellen einer Instanz des ValuePoolFuzzer
    fuzzer = ValuePoolFuzzer()

    # Einfacher Aufruf der fuzz-Methode
    result = fuzzer.fuzz(types=["UINT", "INT"], param_combi=2)

    # Ausgabe des Rückgabewerts
    print("Fuzzed Values:")
    print(result)

if __name__ == "__main__":
    main()