# Build OpenLine Connectors

OpenLine has the receipt primitive. Now it needs useful surfaces.

The goal is simple: make portable receipts easy for normal builders to view, create, attach, and verify.

A receipt should preserve the important parts of a handoff: claim, evidence, action or outcome, issuer, timestamp, parent receipt or dependency, and verification status.

The app layer is open territory.

## Connector ideas

### 1. Receipt Viewer

Drop in a receipt JSON and get a readable card showing claim, evidence, action or outcome, issuer, timestamp, parent chain, and verification status.

Bonus: parent-chain view, signature check, embeddable card, dark mode.

### 2. GitHub Issue / PR Connector

Turn a GitHub issue, pull request, or review into an OpenLine receipt.

Useful outputs:

- “Export as OpenLine Receipt”
- attach receipt to issue comment
- capture claim, change, test, reviewer, and outcome
- preserve parent issue or PR link

### 3. Discovery Market UI

Create an Opportunity Pack and export a receipt.

The form should capture:

- claim
- falsifier
- measurable KPI
- cheapest credible witness
- expected test window
- result / outcome

## Rules

Use any stack.

Next.js, plain HTML/JS, Python, FastAPI, Electron, browser extension, CLI — whatever ships.

Requirements:

- open source
- MIT or Apache 2.0 license
- works with the current OpenLine receipt shape
- includes a simple demo or screenshot
- keeps the receipt portable

## Ownership

Build a useful connector and you can own that connector.

OpenLine can link to strong external connector repos from the main README.

The point is to make receipts travel.

## How to claim one

Comment below with:

- which connector you want to build
- your GitHub handle
- rough ETA
- stack you plan to use

First solid working version gets linked and credited.

Receipts, not rhetoric.
