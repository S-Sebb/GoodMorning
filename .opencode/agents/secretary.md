---
description: Website secretary chats; docs and helper output are its whole contract
mode: primary
hidden: true
permissions:
  - action: read
    resource: "src/*"
    effect: deny
  - action: read
    resource: "scripts/*"
    effect: deny
  - action: read
    resource: "tests/*"
    effect: deny
  - action: read
    resource: "*/src/goodmorning/*"
    effect: deny
  - action: read
    resource: "*/tests/*"
    effect: deny
  - action: glob
    resource: "*.py"
    effect: deny
  - action: shell
    resource: "* src/*"
    effect: deny
  - action: shell
    resource: "* tests/*"
    effect: deny
  - action: shell
    resource: "*/src/goodmorning*"
    effect: deny
  - action: shell
    resource: "*/tests/*"
    effect: deny
  - action: shell
    resource: "*PYTHONPATH=*"
    effect: deny
  - action: shell
    resource: "*import goodmorning*"
    effect: deny
  - action: shell
    resource: "*from goodmorning*"
    effect: deny
---
