# Emotions in Student–LLM Conversations During a Hackathon

Code and prompts for the paper *Emotions in Student–LLM Conversations During a Hackathon*.
Emotions are annotated turn by turn by three LLMs (Qwen 2.5-14B, Mistral-Nemo, Gemma-9B)
with majority voting, then analysed for distribution, transitions, and links to performance.

## Structure

```
├── Paper_Research          # Final Article
├── analysis.ipynb          # all analyses and figures
├── prompts/                # annotation prompts (in French)
└── annotation/
    ├── hackathon_emotion/  # emotion annotation, hackathon
    ├── hackathon_action/   # action annotation, hackathon
    └── studychat/          # emotion annotation, StudyChat
└── Scraping /
    ├── scrape_conversation/ # functions for scraping
    ├── cleaning/ # cleaning of the DataSet
    └── chatgpt_cookies/ # necessary cookies in order to connect to a website (for scraping)

```

Each `annotation/` subfolder holds the vLLM annotation script, the per-model
outputs, and `merge.py` (majority vote). Annotation uses a 16-turn context
window at temperature 0.

## Data schema

Conversations are **not** included (GDPR). The analyses expect two tables:

**`df_turns.csv`** — one row per turn: `Id` (conversation), `Turn_id`, `User`,
`Assistant`, `emotion_user` (voted emotion).

**`df_conversations.csv`** — one row per conversation: `Id`, `grade`, `niveau`
(Low / Medium / High), plus one column per emotion (proportion of turns).

StudyChat is public: McNichols, Ikram, and Lan, *The StudyChat dataset* (LAK 2026).

## Reproduce

Run the annotation script then `merge.py` in each `annotation/` subfolder, then
run `analysis.ipynb` top to bottom.
