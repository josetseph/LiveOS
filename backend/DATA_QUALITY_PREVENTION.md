# Data Quality Prevention Documentation

## Overview
This document explains the automated data validation system that prevents common data quality issues in the knowledge graph during ingestion.

## Issues Prevented

### 1. Task Status Fragmentation
**Problem**: LLM extraction produces 21+ different status variations (null, complete, completed, COMPLETED, done, DONE, TODO, todo, pending, Pending, PENDING, open, finished, x, ❌, etc.)

**Solution**: All task statuses are automatically standardized to one of 4 canonical values:
- `Todo` - Not started, pending, open
- `Complete` - Done, finished, closed
- `In Progress` - Active, ongoing, in-progress
- `Cancelled` - Blocked, abandoned, canceled

**Implementation**:
- Status mapping dictionary in [`app/utils/data_validation.py`](app/utils/data_validation.py)
- Applied automatically in [`extraction_node()`](app/workflows/agents/ingestion_agent.py) after LLM extraction
- LLM prompt updated to guide toward standardized values
- Schema default changed from "Pending" → "Todo"

### 2. Redundant Task Naming
**Problem**: Tasks used `name = description`, creating redundant structure and poor graph visualization

**Solution**: Unique task names generated using format: `description[:50]_uuid[:8]`
- First 50 characters of description for readability
- First 8 characters of UUID for uniqueness
- Prevents duplicate task names in graph

**Implementation**:
- `generate_unique_task_name()` function in [`app/utils/data_validation.py`](app/utils/data_validation.py)
- Applied in [`_store_graph_nodes()`](app/workflows/ingestion.py) when creating Task nodes
- Each task gets deterministic unique identifier

### 3. Empty Reference Summaries
**Problem**: Reference nodes created with empty `title` field, breaking graph visualization and causing errors

**Solution**: All references validated to have non-empty titles:
- If title empty but content exists: `"Reference: {content[:50]}"`
- If title empty but source exists: `"{type} by {source}"`
- Fallback: `"Untitled {type}"`

**Implementation**:
- `validate_reference_summary()` function in [`app/utils/data_validation.py`](app/utils/data_validation.py)
- Applied in `standardize_extraction()` before graph storage
- Ensures every Reference node has displayable title

## Validation Flow

```
LLM Extraction
      ↓
[extraction_node]
      ↓
standardize_extraction()
      ├─ Standardize task statuses (21 variants → 4 standard)
      └─ Validate reference titles (ensure non-empty)
      ↓
[storage_node]
      ├─ Generate unique task names (description_uuid)
      └─ Store in Neo4j with validated data
```

## Usage

### Automatic (Default)
All new note ingestions automatically apply validation:
1. LLM extracts raw data
2. `standardize_extraction()` normalizes statuses and validates references
3. `generate_unique_task_name()` creates unique task identifiers
4. Clean, standardized data stored in graph

### Manual Testing
Run validation test suite:
```bash
cd backend
source venv/bin/activate
python test_data_validation.py
```

## Files Modified

### Core Validation Utilities
- **`app/utils/data_validation.py`** (NEW)
  - `standardize_task_status()` - Maps 25+ status variants to 4 standard values
  - `generate_unique_task_name()` - Creates unique readable task names
  - `validate_reference_summary()` - Ensures references have titles
  - `standardize_extraction()` - Main validation entry point

### Integration Points
- **`app/workflows/agents/ingestion_agent.py`**
  - Line ~220: Added `standardize_extraction()` call after LLM extraction
  - Line ~150-180: Updated prompt to guide LLM toward standardized values

- **`app/workflows/ingestion.py`**
  - Line ~365-385: Updated task storage to use `generate_unique_task_name()`

- **`app/schemas/extraction.py`**
  - Task.status default changed: `"Pending"` → `"Todo"`
  - Task validator default changed to standardized value

### Testing
- **`backend/test_data_validation.py`** (NEW)
  - Tests status standardization (25 test cases)
  - Tests unique name generation
  - Tests reference validation
  - Tests full extraction pipeline

## Standardized Values Reference

### Task Status Values (ONLY these 4)
```python
VALID_TASK_STATUSES = {
    "Todo",        # Not started
    "Complete",    # Finished
    "In Progress", # Currently working
    "Cancelled"    # Won't do
}
```

### Status Mapping Examples
```python
"done" → "Complete"
"TODO" → "Todo"
"in-progress" → "In Progress"
"blocked" → "Cancelled"
None → "Todo"
"weird_status" → "Todo" (fallback)
```

## Benefits

1. **Consistent Queries**: Can reliably filter by status without checking multiple variants
2. **Better Visualization**: Graph nodes have unique, readable names
3. **No Empty Nodes**: All references guaranteed to have displayable titles
4. **Future-Proof**: New status variations automatically mapped to standard values
5. **LLM Guidance**: Prompt instructs model to use standard values from the start

## Maintenance

### Adding New Status Variants
If LLM produces new status variations, add to `STATUS_MAPPING` in [`app/utils/data_validation.py`](app/utils/data_validation.py):

```python
STATUS_MAPPING = {
    "new_variant": "Todo",  # Map to appropriate standard value
    ...
}
```

### Changing Standard Values
**NOT RECOMMENDED** - Would require migrating existing graph data. Instead, add variants to existing mappings.

## Verification

After ingestion, verify standardization:

```cypher
// Check task status distribution (should only see 4 values)
MATCH (t:Task)
RETURN t.status, count(*) as count
ORDER BY count DESC

// Verify unique task names
MATCH (t:Task)
WITH t.name as name, collect(t) as tasks
WHERE size(tasks) > 1
RETURN name, size(tasks) as duplicates

// Check for empty reference titles
MATCH (r:Reference)
WHERE r.title IS NULL OR r.title = ''
RETURN count(*) as empty_titles
```

Expected results:
- Only 4 status values: "Todo", "Complete", "In Progress", "Cancelled"
- No duplicate task names
- Zero empty reference titles
