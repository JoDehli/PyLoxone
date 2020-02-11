# PyLoxone
Home Assistant binding for Loxone. 

#### This release works for the version 0.103.0 and newer!!

## Installation
Copy all the files and subfolders to your custom_components folder in your HomeAssistant
main folder. All you have to define is the following section:

```yaml
loxone:
  port: 8080
  host: hostadress
  username: username
  password: password
  generate_scenes: false # default is true
```

A special thanks to Pawel Pieczul from the great openhab2 house automation software. 
He really helped me a lot to with the new token based authentification. Thanks Pawel!!!

## Websocket direct command
Send command direct to the loxone for example a pulse event to a switch:

```yaml
{
"uuid":"0f1e0b31-0179-7f77-ffff403fb0c34b9e",
"value":"pulse"
}
```
