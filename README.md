# PyLoxone
Home Assistant binding for Loxone.

## Wozu dient dieses Binding:
Meine Loxone verrichtet ausgezeichnete Arbeit in meinem Haus. Leider
ist es nicht so einfach, weitere Komponenten fremder Hersteller in das Loxone
System einzubinden. Deshalb benutze ich für alle weiteren Komponenten Home Assistant
als Hausautomation. Durch diese kleine Schnittstelle ist es möglich, bestimmte Komponenten
der Loxone in Home Assistant zu integrieren. 

## Was wird zur Installation benötigt:
Leider habe ich es noch nicht geschafft die neueste Authentifzierungs Methode von Loxone in
diese Schnittstelle zu integrieren. Deshalb muss ich den Umweg über Node Red und die dazugehörige
Loxone Schnittstelle gehen (https://github.com/codmpm/node-red-contrib-loxone). Alle Loxone Events
werden dadurch auf einen MQTT Channel gestreamt und dann an Home Assistant weiter geleitet. 

* Loxone Miniserver
* Raspberry Pi
* Home Assistant Installation (Installationhinweise hier: https://home-assistant.io/)
* Node Red installation (Installationshinweise hier: https://nodered.org/docs/getting-started/installation)
* Mqtt Installation



