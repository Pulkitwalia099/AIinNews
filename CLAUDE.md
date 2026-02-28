# AI Newsletter Project

## What we're building
A daily AI/tech newsletter for builders — curated by Claude, published on a public website.

## Audience
Builders exploring ideas — whether that's a startup, a class project, a career move, or a product feature.

## Newsletter structure
Each article is processed into:
- **Section**: Foundational | Infra | Application | Research
- **Tags**:
  - Signal type: Opportunity, Enabler, Disruption, Platform Shift, Cost Driver, New Market
  - Maturity: Early Research, Emerging, Production-Ready
- **Summary**: 2-3 sentences
- **Builder's Lens**: 1 paragraph — what this means for what you're building

## Tech stack
- Python pipeline (fetch → process → save)
- Claude API for curation and analysis
- Flask for the public website
- JSON for storing newsletter issues

## Project phases
1. Content pipeline (RSS → Claude → JSON)
2. Website (Flask + HTML)
3. Email sending
4. Automation (daily scheduling)

## Learning outcomes
- API calls and the Anthropic SDK
- JSON (structured data format)
- Config files (separation of config from code)
- Prompt engineering (getting Claude to output structured analysis)
- Error handling
- Flask web basics
- HTML/CSS fundamentals
- Automation with scheduling

## File structure (planned)
```
ai-newsletter/
├── config.json        # RSS feed URLs and settings
├── fetch.py           # Pulls articles from RSS feeds
├── process.py         # Sends articles to Claude, gets structured output
├── generate.py        # Formats newsletter into final output
├── app.py             # Flask website
├── templates/         # HTML templates
└── newsletters/       # Saved newsletter JSON files
```
