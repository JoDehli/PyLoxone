import hashlib

def hash_string_md5(input_string: str) -> str:
    md5_hash = hashlib.md5()
    md5_hash.update(input_string.encode('utf-8'))
    return md5_hash.hexdigest()

# Beispiel:
input_string = "Hello, world!"
hashed_string = hash_string_md5(input_string)
print(f"Der MD5-Hash von '{input_string}' ist: {hashed_string}")
