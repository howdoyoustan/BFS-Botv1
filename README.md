# BFS-Botv1
Cross Functional Incident Triage

TASK: find common ground in these three approaches (1, 2, 3) to create and maintain a personal AI assistant/knowledge-base. I'm an Obsidian + Zotero user, and my KB tree can be queried with `obsidian-cli` (or just filesystem search at ~/Notes/) and `zotero-mcp` (my library is a group library with ID *****). My goal with this brain project is to batch import everything into Obsidian's vault and ditch Zotero once done, letting the AI assistant manage my entire knowledge base.

  1- https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f
  2- https://github.com/garrytan/gbrain
  3- https://github.com/danielmiessler/Personal_AI_Infrastructure

  Start from the index/readme and checkout the repos only if needed.
  
  ---

  Here are some of my positions:

  - Daniel Miessler's PAI: I like the "current state" vs "desired state" idea, and the Telos goal framework:
  https://github.com/danielmiessler/Personal_AI_Infrastructure/tree/main/Packs/Telos but I don't like the strong dependency
  on Claude (I prefer Pi so I'm free to use any model/provider)

  - GBrain: I like the self-improving aspect, which is achieved via Hermes' built-in self-improve/sleep cycles, but I guess
  it can be obtained with Pi and scheduled jobs. I don't like the opinionated content structure, because it's heavily
  personal and based on its role at Y-Combinator. For that, my Obsidian + Google Drive structure mirrors my habits,
  although it needs to be simplified a bit because it has too many levels deep.

  - Karpathy's idea: I like the fact that it can work on Obsidian and that it's simple, flexible, adaptable, not
  prescriptive.
  
Ask me more questions beyond what can be seen in ~/.claude/CLAUDE.md if you're unsure.

https://github.com/axoviq-ai/synthadoc#readme

