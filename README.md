# YAMill

> Grinding down your YAML.

YAMill is an uncompromizing formatter for YAML.  There is only one way YAMill represents the same data.  

The main goal of YAMill is to output YAML that is easy to read and understand _for humans_.  To achieve this YAMill avoids verbose syntax and possibly ambiguos looking constructs.  
A secondary goal is to keep changes to the output at a minimum when input data is changed.  

YAMill also introduces some restrictions, with the same goals in mind:
- Only one YAML document per file
- No user defined data types (aka. tags)
- No non-string mapping keys

## Example

```yaml
# This is what a YAMill formatted document looks like.
some: 'things'
"ain't":
  - 42  # the answer
  -
    - 0.14
```
