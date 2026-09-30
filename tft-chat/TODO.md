
condense all routing into a single, mid-size agent. deterministic selection for context, skills, anything else, then layout `routing_rules` so that we can define a bunch of boundary conditions. realistically this will becomne quite a long list of disjoint rules, but for this purpose it seems fine and maintainable just given the function. Also seems like less effort than trying to do some super precise determinstic selection. E.g. if the user wants the best artifact items, I don't want a bunch of random artifact items and their definitions to be ranked as relevant and then top 5 similarity are chosen and shoved into prompt. Noen of the specfiic defintions actually need to be included in that example


I thinkt that there's something wrong with A magic rool. it says that 626 can give a golden egg


- handle mid-patch updates (currently, all things are normalized to base patch number e.g 16.13.1 -> 16.13)

- add naming conventions to AGENTS.md

    loaders
    discovers
    runtime
    models
    utils
 
 - include classes because those are actually pretty important (both explain the definitions and list them next to unit context)
- code clean up later -> wasting too much time trying to keep it perfect along the way

- Assistants system has ended up with code that technically works but has conflicting design intents. 
We have to clean it up and make it cohesive


- WISPS!!
- address the context provider thing in the specs


Terminology to incorporate: 
- "builds" generally does refers to 3-item combinations on a unit
- AD -> Attack Damage
- AP -> Ability Power
- MR -> Default to assuming it means Magic Resistance. It some contexts, the user may mean Mana Regen
- AR -> Armor
- AS -> Attack Speed
- BIS -> Best-in-slot (the best item(s) for a unit)
- component -> item primitive
- spatula / pan 

Most of the time, a "high" placement should be interpreted as a good palcement, not a _numerically_ high placement such as a bottom 4. The converse is true for a "low" placement. It may be used the opposite way, but only assume so if the context strongly points to the other usage.You may see it d It must be interpreted within context.
However, qualitative descriptors (good/bad, strong/weak, etc) will always assign a positive connotation 

Confirm / decide on what we want to go with for relative delta definition. Should it be `placement(entity within cohort) - placement (entity outside of the cohort)` or `placement(entity within cohort) - placement(entity)` 