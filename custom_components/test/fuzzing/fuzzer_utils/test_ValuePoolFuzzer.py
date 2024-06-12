from ValuePoolFuzzer import ValuePoolFuzzer

def main():
    # Erstellen einer Instanz des ValuePoolFuzzer
    fuzzer = ValuePoolFuzzer()

    # Einfacher Aufruf der fuzz-Methode
    result = fuzzer.fuzz(types=["UINT", "INT", "UINT"], param_combi=2)

    # Ausgabe des Rückgabewerts
    print("Fuzzed Values:")
    print(result)

if __name__ == "__main__":
    main()



"""
    l = 0
    x = 0
    while l < len(return_lists):
        m = param_combi
        while m < len(value_pools):
            if x == len(value_pools[m]):
                x = 0
            return_lists[l].append(value_pools[m][x])
            m += 1
        l += 1
        x += 1
"""