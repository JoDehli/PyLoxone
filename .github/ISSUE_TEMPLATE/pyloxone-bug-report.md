---
name: PyLoxone Bug report
about: Create a report to help us improve
title: ''
labels: ''
assignees: ''

---

**Which Model do you use from loxone? Miniserver? Gen1 or Gen2?**

**Which software version does your loxone use?**

**How did you install HomeAssistant? Over Hassio oder manual install?**

**Which Version do you use of HomeAssistant?**

**Describe the bug**
A clear and concise description of what the bug is.

**Paste the error log with the following settings:**
```yaml
logger:
  default: warning
  logs:
    homeassistant: warning
    homeassistant.helpers: warning
    custom_components.loxone: debug
    custom_components.loxone.api: debug
```
