# PyLoxone
Home Assistant binding for Loxone. (Very early state!!)

## Installation
Copy all the files and subfolders to your custom_components folder in your HomeAssistant
main folder. All you have to define is the following section:

```yaml
loxone:
  port: 8080
  host: hostadress
  username: username
  password: password
```

This is a very early stage of the binding. I have not tested it very much. 

A special thanks to Pawel Pieczul from the great openhab2 house automation software. 
He really helped me a lot to with the new token based authentification. Thanks Pawel!!!

