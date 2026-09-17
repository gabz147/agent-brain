---
status: active
project: meta
type: index
updated_by: astra
updated: 2026-09-16
---
# Brain

[[VAULT-INDEX|Vault map]] | [[Active Priorities|Full queue]] | [[Decisions]] | [[Dead Ends]] | [[Vault Actions|On-demand actions]]

## Now

![[Active Priorities#Active Now]]

## Next

![[Active Priorities#Next]]

## Topic notes

```base
filters:
  and:
    - 'file.ext == "md"'
    - '!file.inFolder("09 - Archive")'
    - 'type != "index"'
    - 'type != "log"'
    - 'file.name != "Active Priorities"'
properties:
  file.name:
    displayName: Note
  note.updated:
    displayName: Last edited
views:
  - type: table
    name: Active topics
    filters: 'status == "active"'
    groupBy:
      property: note.project
      direction: ASC
    order:
      - file.name
      - note.status
      - note.updated
  - type: table
    name: All topics
    groupBy:
      property: note.project
      direction: ASC
    order:
      - file.name
      - note.status
      - note.updated
```

Last edited records a note change, not verification of every claim. [[Vault Actions#Evidence freshness|Record evidence freshness]] when it matters.

## Waiting and review

[[Active Priorities#Waiting|Waiting on inputs or acceptance]] | [[Active Priorities#Review|Items needing a decision]] | [[Active Priorities#Parked / Watch|Parked / watch]]
