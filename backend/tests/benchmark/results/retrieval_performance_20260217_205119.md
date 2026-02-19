# Retrieval & Ranking Performance Test Report

- Generated At: `2026-02-17T20:51:19`
- Script: `test_retrieval_performance.py`

---

## Test 1

**Query:** Were Scott Derrickson and Ed Wood of the same nationality?

- Retrieval Time: `11.86s`
- Total Results: `12`

### Result Breakdown

- Temporal (Recent Notes): `0`
- Graph Nodes: `0`
- Evidence (Linked Notes): `0`

### Result 1

- Type: `entity_match`
- Label: `🔗 EVIDENCE`
- Score: `0.0000`
- Is Recent: `False`

#### Full Text

```text
[Consensus - Entity: ed wood]: Ed Wood is a 1994 American biographical period comedy-drama film directed and produced by Tim Burton, and starring Johnny Depp as Ed Wood. The film concerns the period in Wood's life when he made his best-known films as well as his relationship with actor Bela Lugosi, played by Martin Landau. Sarah Jessica Parker, Patricia Arquette, Jeffrey Jones, Lisa Marie, and Bill Murray are among the supporting cast.
```

#### Full Payload

```json
{
  "text": "[Consensus - Entity: ed wood]: Ed Wood is a 1994 American biographical period comedy-drama film directed and produced by Tim Burton, and starring Johnny Depp as Ed Wood. The film concerns the period in Wood's life when he made his best-known films as well as his relationship with actor Bela Lugosi, played by Martin Landau. Sarah Jessica Parker, Patricia Arquette, Jeffrey Jones, Lisa Marie, and Bill Murray are among the supporting cast.",
  "type": "entity_match",
  "original_obj": {
    "name": "ed wood",
    "labels": [
      "Entity",
      "Indexable"
    ],
    "summary": "Ed Wood is a 1994 American biographical period comedy-drama film directed and produced by Tim Burton, and starring Johnny Depp as Ed Wood. The film concerns the period in Wood's life when he made his best-known films as well as his relationship with actor Bela Lugosi, played by Martin Landau. Sarah Jessica Parker, Patricia Arquette, Jeffrey Jones, Lisa Marie, and Bill Murray are among the supporting cast.",
    "description": null,
    "trait": null,
    "status": null,
    "entity_type": "Person",
    "matched_query": "ed wood",
    "_source": "entity_match"
  },
  "is_recent": false,
  "priority": "primary",
  "vector_score": 1.0,
  "linked_notes": [
    {
      "id": "9981be6e-56a3-4a10-b746-22bfbdeb8cdf",
      "content": null,
      "title": "Ed Wood _film_",
      "created_at": "2026-02-14T23:20:30.777090+00:00"
    }
  ],
  "type_score": 1.0,
  "semantic_score": 1.0,
  "combined_score": 1.0,
  "domain_boost": 1.0,
  "final_score": 1.0,
  "rerank_score": 0.0,
  "boosts": {
    "source": "entity_match",
    "domain": 1.0
  }
}
```

### Result 2

- Type: `entity_match`
- Label: `🔗 EVIDENCE`
- Score: `0.0000`
- Is Recent: `False`

#### Full Text

```text
[Consensus - Entity: ed wood sr.]: Ed Wood Sr. was a prominent plantation owner, trader, and businessman at the turn of the 20th century. Woodson and Woodson Lake and Wood Hollow are the namesake for him.
```

#### Full Payload

```json
{
  "text": "[Consensus - Entity: ed wood sr.]: Ed Wood Sr. was a prominent plantation owner, trader, and businessman at the turn of the 20th century. Woodson and Woodson Lake and Wood Hollow are the namesake for him.",
  "type": "entity_match",
  "original_obj": {
    "name": "ed wood sr.",
    "labels": [
      "Entity",
      "Indexable"
    ],
    "summary": "Ed Wood Sr. was a prominent plantation owner, trader, and businessman at the turn of the 20th century. Woodson and Woodson Lake and Wood Hollow are the namesake for him.",
    "description": null,
    "trait": null,
    "status": null,
    "entity_type": "Person",
    "matched_query": "ed wood",
    "_source": "entity_match"
  },
  "is_recent": false,
  "priority": "primary",
  "vector_score": 1.0,
  "linked_notes": [
    {
      "id": "498ef306-3cc6-4033-8f81-05af84a55d99",
      "content": null,
      "title": "Woodson_ Arkansas",
      "created_at": "2026-02-15T05:44:24.624703+00:00"
    }
  ],
  "type_score": 1.0,
  "semantic_score": 1.0,
  "combined_score": 1.0,
  "domain_boost": 1.0,
  "final_score": 1.0,
  "rerank_score": 0.0,
  "boosts": {
    "source": "entity_match",
    "domain": 1.0
  }
}
```

### Result 3

- Type: `entity_match`
- Label: `🔗 EVIDENCE`
- Score: `0.0000`
- Is Recent: `False`

#### Full Text

```text
[Consensus - Entity: scott derrickson]: Scott Derrickson (born July 16, 1966) is an American director, screenwriter, and producer. He lives in Los Angeles, California. He is known for directing horror films such as "Sinister", "The Exorcism of Emily Rose", and "Deliver Us From Evil", as well as "Doctor Strange" (2016). "Sinister" (2012) stars Ethan Hawke. He collaborated with directors like Zack Snyder, Rob Zombie, and James Gunn.
```

#### Full Payload

```json
{
  "text": "[Consensus - Entity: scott derrickson]: Scott Derrickson (born July 16, 1966) is an American director, screenwriter, and producer. He lives in Los Angeles, California. He is known for directing horror films such as \"Sinister\", \"The Exorcism of Emily Rose\", and \"Deliver Us From Evil\", as well as \"Doctor Strange\" (2016). \"Sinister\" (2012) stars Ethan Hawke. He collaborated with directors like Zack Snyder, Rob Zombie, and James Gunn.",
  "type": "entity_match",
  "original_obj": {
    "name": "scott derrickson",
    "labels": [
      "Entity",
      "Indexable"
    ],
    "summary": "Scott Derrickson (born July 16, 1966) is an American director, screenwriter, and producer. He lives in Los Angeles, California. He is known for directing horror films such as \"Sinister\", \"The Exorcism of Emily Rose\", and \"Deliver Us From Evil\", as well as \"Doctor Strange\" (2016). \"Sinister\" (2012) stars Ethan Hawke. He collaborated with directors like Zack Snyder, Rob Zombie, and James Gunn.",
    "description": null,
    "trait": null,
    "status": null,
    "entity_type": "Person",
    "matched_query": "scott derrickson",
    "_source": "entity_match"
  },
  "is_recent": false,
  "priority": "primary",
  "vector_score": 1.0,
  "linked_notes": [
    {
      "id": "08e972b8-b3bb-411b-90c2-cb9695e3d4e2",
      "content": null,
      "title": "Tyler Bates",
      "created_at": "2026-02-16T14:39:11.990771+00:00"
    },
    {
      "id": "00bb3e25-88ec-442c-9ce5-2856708ecd3b",
      "content": null,
      "title": "Adam Collis",
      "created_at": "2026-02-16T06:08:43.470582+00:00"
    }
  ],
  "type_score": 1.0,
  "semantic_score": 1.0,
  "combined_score": 1.0,
  "domain_boost": 1.0,
  "final_score": 1.0,
  "rerank_score": 0.0,
  "boosts": {
    "source": "entity_match",
    "domain": 1.0
  }
}
```

### Result 4

- Type: `vector_match`
- Label: `🔗 EVIDENCE`
- Score: `0.0000`
- Is Recent: `False`

#### Full Text

```text
[Consensus - Entity: johnny depp] (similarity: 0.77): Johnny Depp starred as cult filmmaker Ed Wood in the 1994 film Ed Wood.
```

#### Full Payload

```json
{
  "text": "[Consensus - Entity: johnny depp] (similarity: 0.77): Johnny Depp starred as cult filmmaker Ed Wood in the 1994 film Ed Wood.",
  "type": "vector_match",
  "original_obj": {
    "name": "johnny depp",
    "summary": "Johnny Depp starred as cult filmmaker Ed Wood in the 1994 film Ed Wood.",
    "description": null,
    "trait": null,
    "status": null,
    "entity_type": "Person",
    "labels": [
      "Entity",
      "Indexable"
    ],
    "score": 0.7676825523376465,
    "_source": "vector"
  },
  "is_recent": false,
  "priority": "primary",
  "vector_score": 0.7676825523376465,
  "linked_notes": [
    {
      "id": "9981be6e-56a3-4a10-b746-22bfbdeb8cdf",
      "content": null,
      "title": "Ed Wood _film_",
      "created_at": "2026-02-14T23:20:30.777090+00:00"
    }
  ],
  "type_score": 1.0,
  "semantic_score": 0.7676825523376465,
  "combined_score": 0.8373777866363525,
  "domain_boost": 1.0,
  "final_score": 0.8373777866363525,
  "rerank_score": 0.0,
  "boosts": {
    "source": "vector_match",
    "domain": 1.0
  }
}
```

### Result 5

- Type: `vector_match`
- Label: `🔗 EVIDENCE`
- Score: `0.0000`
- Is Recent: `False`

#### Full Text

```text
[Consensus - Entity: edward davis wood jr.] (similarity: 0.76): Edward Davis Wood Jr. was born on October 10, 1924, and died on December 10, 1978. He was an American filmmaker, actor, writer, producer, and director.
```

#### Full Payload

```json
{
  "text": "[Consensus - Entity: edward davis wood jr.] (similarity: 0.76): Edward Davis Wood Jr. was born on October 10, 1924, and died on December 10, 1978. He was an American filmmaker, actor, writer, producer, and director.",
  "type": "vector_match",
  "original_obj": {
    "name": "edward davis wood jr.",
    "summary": "Edward Davis Wood Jr. was born on October 10, 1924, and died on December 10, 1978. He was an American filmmaker, actor, writer, producer, and director.",
    "description": null,
    "trait": null,
    "status": null,
    "entity_type": "Person",
    "labels": [
      "Entity",
      "Indexable"
    ],
    "score": 0.7562341690063477,
    "_source": "vector"
  },
  "is_recent": false,
  "priority": "primary",
  "vector_score": 0.7562341690063477,
  "linked_notes": [
    {
      "id": "5ac93b57-c743-4f64-996f-ca509f737a7b",
      "content": null,
      "title": "Ed Wood",
      "created_at": "2026-02-16T11:40:18.850359+00:00"
    }
  ],
  "type_score": 1.0,
  "semantic_score": 0.7562341690063477,
  "combined_score": 0.8293639183044434,
  "domain_boost": 1.0,
  "final_score": 0.8293639183044434,
  "rerank_score": 0.0,
  "boosts": {
    "source": "vector_match",
    "domain": 1.0
  }
}
```

### Result 6

- Type: `entity_match`
- Label: `🔗 EVIDENCE`
- Score: `0.0000`
- Is Recent: `False`

#### Full Text

```text
[Consensus - Concept: ed wood films]: Conrad Brooks appeared in Ed Wood films including "Plan 9 from Outer Space", "Glen or Glenda", and "Jail Bait".
```

#### Full Payload

```json
{
  "text": "[Consensus - Concept: ed wood films]: Conrad Brooks appeared in Ed Wood films including \"Plan 9 from Outer Space\", \"Glen or Glenda\", and \"Jail Bait\".",
  "type": "entity_match",
  "original_obj": {
    "name": "ed wood films",
    "labels": [
      "Concept",
      "Indexable"
    ],
    "summary": "Conrad Brooks appeared in Ed Wood films including \"Plan 9 from Outer Space\", \"Glen or Glenda\", and \"Jail Bait\".",
    "description": null,
    "trait": null,
    "status": null,
    "entity_type": null,
    "matched_query": "ed wood",
    "_source": "entity_match"
  },
  "is_recent": false,
  "priority": "primary",
  "vector_score": 1.0,
  "linked_notes": [
    {
      "id": "fabe46aa-b453-4bc1-8620-01e9a5802518",
      "content": null,
      "title": "Conrad Brooks",
      "created_at": "2026-02-16T17:37:24.968432+00:00"
    }
  ],
  "type_score": 0.3,
  "semantic_score": 1.0,
  "combined_score": 0.79,
  "domain_boost": 1.0,
  "final_score": 0.79,
  "rerank_score": 0.0,
  "boosts": {
    "source": "entity_match",
    "domain": 1.0
  }
}
```

### Result 7

- Type: `vector_match`
- Label: `🔗 EVIDENCE`
- Score: `0.0000`
- Is Recent: `False`

#### Full Text

```text
[Consensus - Concept: filmmaker] (similarity: 0.78): Edward Davis Wood Jr. was an American filmmaker, actor, writer, producer, and director. He was born on October 10, 1924, and died on December 10, 1978.
```

#### Full Payload

```json
{
  "text": "[Consensus - Concept: filmmaker] (similarity: 0.78): Edward Davis Wood Jr. was an American filmmaker, actor, writer, producer, and director. He was born on October 10, 1924, and died on December 10, 1978.",
  "type": "vector_match",
  "original_obj": {
    "name": "filmmaker",
    "summary": "Edward Davis Wood Jr. was an American filmmaker, actor, writer, producer, and director. He was born on October 10, 1924, and died on December 10, 1978.",
    "description": null,
    "trait": null,
    "status": null,
    "entity_type": null,
    "labels": [
      "Concept",
      "Indexable"
    ],
    "score": 0.7811474800109863,
    "_source": "vector"
  },
  "is_recent": false,
  "priority": "primary",
  "vector_score": 0.7811474800109863,
  "linked_notes": [
    {
      "id": "5ac93b57-c743-4f64-996f-ca509f737a7b",
      "content": null,
      "title": "Ed Wood",
      "created_at": "2026-02-16T11:40:18.850359+00:00"
    }
  ],
  "type_score": 0.3,
  "semantic_score": 0.7811474800109863,
  "combined_score": 0.6368032360076904,
  "domain_boost": 1.0,
  "final_score": 0.6368032360076904,
  "rerank_score": 0.0,
  "boosts": {
    "source": "vector_match",
    "domain": 1.0
  }
}
```

### Result 8

- Type: `vector_match`
- Label: `🔗 EVIDENCE`
- Score: `0.0000`
- Is Recent: `False`

#### Full Text

```text
[Consensus - Concept: horror films] (similarity: 0.76): Scott Derrickson is an American director, screenwriter, and producer. He is known for directing horror films such as "Sinister", "The Exorcism of Emily Rose", and "Deliver Us From Evil". He also directed the 2016 Marvel Cinematic Universe installment, "Doctor Strange".
```

#### Full Payload

```json
{
  "text": "[Consensus - Concept: horror films] (similarity: 0.76): Scott Derrickson is an American director, screenwriter, and producer. He is known for directing horror films such as \"Sinister\", \"The Exorcism of Emily Rose\", and \"Deliver Us From Evil\". He also directed the 2016 Marvel Cinematic Universe installment, \"Doctor Strange\".",
  "type": "vector_match",
  "original_obj": {
    "name": "horror films",
    "summary": "Scott Derrickson is an American director, screenwriter, and producer. He is known for directing horror films such as \"Sinister\", \"The Exorcism of Emily Rose\", and \"Deliver Us From Evil\". He also directed the 2016 Marvel Cinematic Universe installment, \"Doctor Strange\".",
    "description": null,
    "trait": null,
    "status": null,
    "entity_type": null,
    "labels": [
      "Concept",
      "Indexable"
    ],
    "score": 0.7562747001647949,
    "_source": "vector"
  },
  "is_recent": false,
  "priority": "primary",
  "vector_score": 0.7562747001647949,
  "linked_notes": [
    {
      "id": "d0c81a61-503c-4f90-bd56-8b3a66715b90",
      "content": null,
      "title": "Scott Derrickson",
      "created_at": "2026-02-14T16:18:49.999652+00:00"
    }
  ],
  "type_score": 0.3,
  "semantic_score": 0.7562747001647949,
  "combined_score": 0.6193922901153565,
  "domain_boost": 1.0,
  "final_score": 0.6193922901153565,
  "rerank_score": 0.0,
  "boosts": {
    "source": "vector_match",
    "domain": 1.0
  }
}
```

### Result 9

- Type: `vector_match`
- Label: `🔗 EVIDENCE`
- Score: `0.0000`
- Is Recent: `False`

#### Full Text

```text
[Consensus - Concept: biographical] (similarity: 0.75): In 1994, Ed Wood is an American biographical period comedy-drama film directed by Tim Burton and starring Johnny Depp as Ed Wood.
```

#### Full Payload

```json
{
  "text": "[Consensus - Concept: biographical] (similarity: 0.75): In 1994, Ed Wood is an American biographical period comedy-drama film directed by Tim Burton and starring Johnny Depp as Ed Wood.",
  "type": "vector_match",
  "original_obj": {
    "name": "biographical",
    "summary": "In 1994, Ed Wood is an American biographical period comedy-drama film directed by Tim Burton and starring Johnny Depp as Ed Wood.",
    "description": null,
    "trait": null,
    "status": null,
    "entity_type": null,
    "labels": [
      "Concept",
      "Indexable"
    ],
    "score": 0.7456886768341064,
    "_source": "vector"
  },
  "is_recent": false,
  "priority": "primary",
  "vector_score": 0.7456886768341064,
  "linked_notes": [
    {
      "id": "9981be6e-56a3-4a10-b746-22bfbdeb8cdf",
      "content": null,
      "title": "Ed Wood _film_",
      "created_at": "2026-02-14T23:20:30.777090+00:00"
    }
  ],
  "type_score": 0.3,
  "semantic_score": 0.7456886768341064,
  "combined_score": 0.6119820737838745,
  "domain_boost": 1.0,
  "final_score": 0.6119820737838745,
  "rerank_score": 0.0,
  "boosts": {
    "source": "vector_match",
    "domain": 1.0
  }
}
```

### Result 10

- Type: `vector_match`
- Label: `🔗 EVIDENCE`
- Score: `0.0000`
- Is Recent: `False`

#### Full Text

```text
[Consensus - Entity: wood plantation] (similarity: 0.80): The Wood Plantation is owned by Ed Wood Sr. It is adjacent to Woodson.
```

#### Full Payload

```json
{
  "text": "[Consensus - Entity: wood plantation] (similarity: 0.80): The Wood Plantation is owned by Ed Wood Sr. It is adjacent to Woodson.",
  "type": "vector_match",
  "original_obj": {
    "name": "wood plantation",
    "summary": "The Wood Plantation is owned by Ed Wood Sr. It is adjacent to Woodson.",
    "description": null,
    "trait": null,
    "status": null,
    "entity_type": "Place",
    "labels": [
      "Entity",
      "Indexable"
    ],
    "score": 0.8009035587310791,
    "_source": "vector"
  },
  "is_recent": false,
  "priority": "primary",
  "vector_score": 0.8009035587310791,
  "linked_notes": [
    {
      "id": "498ef306-3cc6-4033-8f81-05af84a55d99",
      "content": null,
      "title": "Woodson_ Arkansas",
      "created_at": "2026-02-15T05:44:24.624703+00:00"
    }
  ],
  "type_score": 0.1,
  "semantic_score": 0.8009035587310791,
  "combined_score": 0.5906324911117554,
  "domain_boost": 1.0,
  "final_score": 0.5906324911117554,
  "rerank_score": 0.0,
  "boosts": {
    "source": "vector_match",
    "domain": 1.0
  }
}
```

### Result 11

- Type: `vector_match`
- Label: `🔗 EVIDENCE`
- Score: `0.0000`
- Is Recent: `False`

#### Full Text

```text
[Consensus - Entity: woodson] (similarity: 0.75): Woodson is a census-designated place (CDP) in Pulaski County, Arkansas. The population was 403 at the 2010 census. It is part of the Little Rock–North Little Rock–Conway Metropolitan Statistical Area. Woodson is named for Ed Wood Sr., a plantation owner and businessman. Woodson is adjacent to the Wood Plantation, the largest of the plantations owned by Ed Wood Sr.
```

#### Full Payload

```json
{
  "text": "[Consensus - Entity: woodson] (similarity: 0.75): Woodson is a census-designated place (CDP) in Pulaski County, Arkansas. The population was 403 at the 2010 census. It is part of the Little Rock–North Little Rock–Conway Metropolitan Statistical Area. Woodson is named for Ed Wood Sr., a plantation owner and businessman. Woodson is adjacent to the Wood Plantation, the largest of the plantations owned by Ed Wood Sr.",
  "type": "vector_match",
  "original_obj": {
    "name": "woodson",
    "summary": "Woodson is a census-designated place (CDP) in Pulaski County, Arkansas. The population was 403 at the 2010 census. It is part of the Little Rock–North Little Rock–Conway Metropolitan Statistical Area. Woodson is named for Ed Wood Sr., a plantation owner and businessman. Woodson is adjacent to the Wood Plantation, the largest of the plantations owned by Ed Wood Sr.",
    "description": null,
    "trait": null,
    "status": null,
    "entity_type": "Place",
    "labels": [
      "Entity",
      "Indexable"
    ],
    "score": 0.7545144557952881,
    "_source": "vector"
  },
  "is_recent": false,
  "priority": "primary",
  "vector_score": 0.7545144557952881,
  "linked_notes": [
    {
      "id": "498ef306-3cc6-4033-8f81-05af84a55d99",
      "content": null,
      "title": "Woodson_ Arkansas",
      "created_at": "2026-02-15T05:44:24.624703+00:00"
    }
  ],
  "type_score": 0.1,
  "semantic_score": 0.7545144557952881,
  "combined_score": 0.5581601190567017,
  "domain_boost": 1.0,
  "final_score": 0.5581601190567017,
  "rerank_score": 0.0,
  "boosts": {
    "source": "vector_match",
    "domain": 1.0
  }
}
```

### Result 12

- Type: `vector_match`
- Label: `🔗 EVIDENCE`
- Score: `0.0000`
- Is Recent: `False`

#### Full Text

```text
[Consensus - Entity: los angeles, california] (similarity: 0.75): Scott Derrickson lives in Los Angeles, California.
```

#### Full Payload

```json
{
  "text": "[Consensus - Entity: los angeles, california] (similarity: 0.75): Scott Derrickson lives in Los Angeles, California.",
  "type": "vector_match",
  "original_obj": {
    "name": "los angeles, california",
    "summary": "Scott Derrickson lives in Los Angeles, California.",
    "description": null,
    "trait": null,
    "status": null,
    "entity_type": "Place",
    "labels": [
      "Entity",
      "Indexable"
    ],
    "score": 0.7532939910888672,
    "_source": "vector"
  },
  "is_recent": false,
  "priority": "primary",
  "vector_score": 0.7532939910888672,
  "linked_notes": [
    {
      "id": "d0c81a61-503c-4f90-bd56-8b3a66715b90",
      "content": null,
      "title": "Scott Derrickson",
      "created_at": "2026-02-14T16:18:49.999652+00:00"
    }
  ],
  "type_score": 0.1,
  "semantic_score": 0.7532939910888672,
  "combined_score": 0.557305793762207,
  "domain_boost": 1.0,
  "final_score": 0.557305793762207,
  "rerank_score": 0.0,
  "boosts": {
    "source": "vector_match",
    "domain": 1.0
  }
}
```

### Score Distribution

- Highest: `0.0000`
- Lowest: `0.0000`
- Average: `0.0000`

### Relevance Check

- `10/10` top results contain query terms (`100%`)

### Weighted Scoring Verification

- Results correctly sorted by weighted final_score (descending): `True`
- Entity-matched results: `0/12`
- Detected query entities: `['Were', 'Scott', 'Derrickson', 'Ed', 'Wood']`
- Keyword-matched results: `0/12`
- Temporal query boost applied: `False`

---

## Test 2

**Query:** What government position was held by the woman who portrayed Corliss Archer in the film Kiss and Tell?

- Retrieval Time: `7.95s`
- Total Results: `8`

### Result Breakdown

- Temporal (Recent Notes): `0`
- Graph Nodes: `0`
- Evidence (Linked Notes): `0`

### Result 1

- Type: `entity_match`
- Label: `🔗 EVIDENCE`
- Score: `0.0000`
- Is Recent: `False`

#### Full Text

```text
[Consensus - Entity: corliss archer]: Corliss Archer was a radio program that ran from January 7, 1943 to September 30, 1956. It was initially CBS's answer to NBC's "A Date with Judy" and was broadcast by NBC in 1948. From October 3, 1952 to June 26, 1953, it aired on ABC before returning to CBS. Fewer than 24 episodes are known to exist. Corliss Archer starred Shirley Temple in the 1945 film Kiss and Tell, when she was 17 years old.
```

#### Full Payload

```json
{
  "text": "[Consensus - Entity: corliss archer]: Corliss Archer was a radio program that ran from January 7, 1943 to September 30, 1956. It was initially CBS's answer to NBC's \"A Date with Judy\" and was broadcast by NBC in 1948. From October 3, 1952 to June 26, 1953, it aired on ABC before returning to CBS. Fewer than 24 episodes are known to exist. Corliss Archer starred Shirley Temple in the 1945 film Kiss and Tell, when she was 17 years old.",
  "type": "entity_match",
  "original_obj": {
    "name": "corliss archer",
    "labels": [
      "Entity",
      "Indexable"
    ],
    "summary": "Corliss Archer was a radio program that ran from January 7, 1943 to September 30, 1956. It was initially CBS's answer to NBC's \"A Date with Judy\" and was broadcast by NBC in 1948. From October 3, 1952 to June 26, 1953, it aired on ABC before returning to CBS. Fewer than 24 episodes are known to exist. Corliss Archer starred Shirley Temple in the 1945 film Kiss and Tell, when she was 17 years old.",
    "description": null,
    "trait": null,
    "status": null,
    "entity_type": "Person",
    "matched_query": "corliss archer",
    "_source": "entity_match"
  },
  "is_recent": false,
  "priority": "primary",
  "vector_score": 1.0,
  "linked_notes": [
    {
      "id": "bd0767e5-067c-44d0-a5f6-4b41ec16e984",
      "content": null,
      "title": "Kiss and Tell _1945 film_",
      "created_at": "2026-02-16T01:22:03.910870+00:00"
    },
    {
      "id": "0dbdbb4e-257f-41e7-9fc8-386437d897cf",
      "content": null,
      "title": "Meet Corliss Archer",
      "created_at": "2026-02-15T13:10:30.135080+00:00"
    }
  ],
  "type_score": 1.0,
  "semantic_score": 1.0,
  "combined_score": 1.0,
  "domain_boost": 1.0,
  "final_score": 1.0,
  "rerank_score": 0.0,
  "boosts": {
    "source": "entity_match",
    "domain": 1.0
  }
}
```

### Result 2

- Type: `vector_match`
- Label: `🔗 EVIDENCE`
- Score: `0.0000`
- Is Recent: `False`

#### Full Text

```text
[Consensus - Entity: shirley temple] (similarity: 0.76): Shirley Temple starred in 'A Kiss for Corliss' (1949) as well as 'Kiss and Tell' (1945). She was 17 years old in 'Kiss and Tell'.
```

#### Full Payload

```json
{
  "text": "[Consensus - Entity: shirley temple] (similarity: 0.76): Shirley Temple starred in 'A Kiss for Corliss' (1949) as well as 'Kiss and Tell' (1945). She was 17 years old in 'Kiss and Tell'.",
  "type": "vector_match",
  "original_obj": {
    "name": "shirley temple",
    "summary": "Shirley Temple starred in 'A Kiss for Corliss' (1949) as well as 'Kiss and Tell' (1945). She was 17 years old in 'Kiss and Tell'.",
    "description": null,
    "trait": null,
    "status": null,
    "entity_type": "Person",
    "labels": [
      "Entity",
      "Indexable"
    ],
    "score": 0.7628390789031982,
    "_source": "vector"
  },
  "is_recent": false,
  "priority": "primary",
  "vector_score": 0.7628390789031982,
  "linked_notes": [
    {
      "id": "bd0767e5-067c-44d0-a5f6-4b41ec16e984",
      "content": null,
      "title": "Kiss and Tell _1945 film_",
      "created_at": "2026-02-16T01:22:03.910870+00:00"
    },
    {
      "id": "977f7b83-a88a-4695-9dfb-49b35d4025bb",
      "content": null,
      "title": "A Kiss for Corliss",
      "created_at": "2026-02-14T22:52:01.378098+00:00"
    }
  ],
  "type_score": 1.0,
  "semantic_score": 0.7628390789031982,
  "combined_score": 0.8339873552322388,
  "domain_boost": 1.0,
  "final_score": 0.8339873552322388,
  "rerank_score": 0.0,
  "boosts": {
    "source": "vector_match",
    "domain": 1.0
  }
}
```

### Result 3

- Type: `vector_match`
- Label: `🔗 EVIDENCE`
- Score: `0.0000`
- Is Recent: `False`

#### Full Text

```text
[Consensus - Entity: richard wallace] (similarity: 0.75): A Kiss for Corliss is a 1949 American comedy film directed by Richard Wallace and written by Howard Dimsdale.
```

#### Full Payload

```json
{
  "text": "[Consensus - Entity: richard wallace] (similarity: 0.75): A Kiss for Corliss is a 1949 American comedy film directed by Richard Wallace and written by Howard Dimsdale.",
  "type": "vector_match",
  "original_obj": {
    "name": "richard wallace",
    "summary": "A Kiss for Corliss is a 1949 American comedy film directed by Richard Wallace and written by Howard Dimsdale.",
    "description": null,
    "trait": null,
    "status": null,
    "entity_type": "Person",
    "labels": [
      "Entity",
      "Indexable"
    ],
    "score": 0.7523529529571533,
    "_source": "vector"
  },
  "is_recent": false,
  "priority": "primary",
  "vector_score": 0.7523529529571533,
  "linked_notes": [
    {
      "id": "977f7b83-a88a-4695-9dfb-49b35d4025bb",
      "content": null,
      "title": "A Kiss for Corliss",
      "created_at": "2026-02-14T22:52:01.378098+00:00"
    }
  ],
  "type_score": 1.0,
  "semantic_score": 0.7523529529571533,
  "combined_score": 0.8266470670700073,
  "domain_boost": 1.0,
  "final_score": 0.8266470670700073,
  "rerank_score": 0.0,
  "boosts": {
    "source": "vector_match",
    "domain": 1.0
  }
}
```

### Result 4

- Type: `vector_match`
- Label: `🔗 EVIDENCE`
- Score: `0.0000`
- Is Recent: `False`

#### Full Text

```text
[Consensus - Entity: howard dimsdale] (similarity: 0.73): A Kiss for Corliss is a 1949 American comedy film directed by Richard Wallace and written by Howard Dimsdale.
```

#### Full Payload

```json
{
  "text": "[Consensus - Entity: howard dimsdale] (similarity: 0.73): A Kiss for Corliss is a 1949 American comedy film directed by Richard Wallace and written by Howard Dimsdale.",
  "type": "vector_match",
  "original_obj": {
    "name": "howard dimsdale",
    "summary": "A Kiss for Corliss is a 1949 American comedy film directed by Richard Wallace and written by Howard Dimsdale.",
    "description": null,
    "trait": null,
    "status": null,
    "entity_type": "Person",
    "labels": [
      "Entity",
      "Indexable"
    ],
    "score": 0.7349076271057129,
    "_source": "vector"
  },
  "is_recent": false,
  "priority": "primary",
  "vector_score": 0.7349076271057129,
  "linked_notes": [
    {
      "id": "977f7b83-a88a-4695-9dfb-49b35d4025bb",
      "content": null,
      "title": "A Kiss for Corliss",
      "created_at": "2026-02-14T22:52:01.378098+00:00"
    }
  ],
  "type_score": 1.0,
  "semantic_score": 0.7349076271057129,
  "combined_score": 0.8144353389739991,
  "domain_boost": 1.0,
  "final_score": 0.8144353389739991,
  "rerank_score": 0.0,
  "boosts": {
    "source": "vector_match",
    "domain": 1.0
  }
}
```

### Result 5

- Type: `entity_match`
- Label: `🔗 EVIDENCE`
- Score: `0.0000`
- Is Recent: `False`

#### Full Text

```text
[Consensus - Entity: kiss and tell]: A Kiss for Corliss is a 1949 American comedy film directed by Richard Wallace and written by Howard Dimsdale. It stars Shirley Temple. It is a sequel to the 1945 film "Kiss and Tell".
```

#### Full Payload

```json
{
  "text": "[Consensus - Entity: kiss and tell]: A Kiss for Corliss is a 1949 American comedy film directed by Richard Wallace and written by Howard Dimsdale. It stars Shirley Temple. It is a sequel to the 1945 film \"Kiss and Tell\".",
  "type": "entity_match",
  "original_obj": {
    "name": "kiss and tell",
    "labels": [
      "Entity",
      "Indexable"
    ],
    "summary": "A Kiss for Corliss is a 1949 American comedy film directed by Richard Wallace and written by Howard Dimsdale. It stars Shirley Temple. It is a sequel to the 1945 film \"Kiss and Tell\".",
    "description": null,
    "trait": null,
    "status": null,
    "entity_type": "Poem",
    "matched_query": "kiss and tell",
    "_source": "entity_match"
  },
  "is_recent": false,
  "priority": "primary",
  "vector_score": 1.0,
  "linked_notes": [
    {
      "id": "977f7b83-a88a-4695-9dfb-49b35d4025bb",
      "content": null,
      "title": "A Kiss for Corliss",
      "created_at": "2026-02-14T22:52:01.378098+00:00"
    }
  ],
  "type_score": 0.1,
  "semantic_score": 1.0,
  "combined_score": 0.73,
  "domain_boost": 1.0,
  "final_score": 0.73,
  "rerank_score": 0.0,
  "boosts": {
    "source": "entity_match",
    "domain": 1.0
  }
}
```

### Result 6

- Type: `vector_match`
- Label: `🔗 EVIDENCE`
- Score: `0.0000`
- Is Recent: `False`

#### Full Text

```text
[Consensus - Concept: television sitcom] (similarity: 0.76): Meet Corliss Archer is an American television sitcom that aired on CBS from July 13, 1951, to August 10, 1951, and in syndication via the Ziv Company from April to December 1954.
```

#### Full Payload

```json
{
  "text": "[Consensus - Concept: television sitcom] (similarity: 0.76): Meet Corliss Archer is an American television sitcom that aired on CBS from July 13, 1951, to August 10, 1951, and in syndication via the Ziv Company from April to December 1954.",
  "type": "vector_match",
  "original_obj": {
    "name": "television sitcom",
    "summary": "Meet Corliss Archer is an American television sitcom that aired on CBS from July 13, 1951, to August 10, 1951, and in syndication via the Ziv Company from April to December 1954.",
    "description": null,
    "trait": null,
    "status": null,
    "entity_type": null,
    "labels": [
      "Concept",
      "Indexable"
    ],
    "score": 0.7564682960510254,
    "_source": "vector"
  },
  "is_recent": false,
  "priority": "primary",
  "vector_score": 0.7564682960510254,
  "linked_notes": [
    {
      "id": "1c1e0cff-f9c3-4008-83d4-a1d76a62ef97",
      "content": null,
      "title": "Meet Corliss Archer _TV series_",
      "created_at": "2026-02-16T01:06:15.300487+00:00"
    }
  ],
  "type_score": 0.3,
  "semantic_score": 0.7564682960510254,
  "combined_score": 0.6195278072357178,
  "domain_boost": 1.0,
  "final_score": 0.6195278072357178,
  "rerank_score": 0.0,
  "boosts": {
    "source": "vector_match",
    "domain": 1.0
  }
}
```

### Result 7

- Type: `vector_match`
- Label: `🔗 EVIDENCE`
- Score: `0.0000`
- Is Recent: `False`

#### Full Text

```text
[Consensus - Concept: comedy film] (similarity: 0.75): A 1949 American comedy film directed by Richard Wallace and written by Howard Dimsdale.
```

#### Full Payload

```json
{
  "text": "[Consensus - Concept: comedy film] (similarity: 0.75): A 1949 American comedy film directed by Richard Wallace and written by Howard Dimsdale.",
  "type": "vector_match",
  "original_obj": {
    "name": "comedy film",
    "summary": "A 1949 American comedy film directed by Richard Wallace and written by Howard Dimsdale.",
    "description": null,
    "trait": null,
    "status": null,
    "entity_type": null,
    "labels": [
      "Concept",
      "Indexable"
    ],
    "score": 0.754389762878418,
    "_source": "vector"
  },
  "is_recent": false,
  "priority": "primary",
  "vector_score": 0.754389762878418,
  "linked_notes": [
    {
      "id": "977f7b83-a88a-4695-9dfb-49b35d4025bb",
      "content": null,
      "title": "A Kiss for Corliss",
      "created_at": "2026-02-14T22:52:01.378098+00:00"
    }
  ],
  "type_score": 0.3,
  "semantic_score": 0.754389762878418,
  "combined_score": 0.6180728340148925,
  "domain_boost": 1.0,
  "final_score": 0.6180728340148925,
  "rerank_score": 0.0,
  "boosts": {
    "source": "vector_match",
    "domain": 1.0
  }
}
```

### Result 8

- Type: `vector_match`
- Label: `🔗 EVIDENCE`
- Score: `0.0000`
- Is Recent: `False`

#### Full Text

```text
[Consensus - Concept: sequel] (similarity: 0.75): A Kiss for Corliss is a 1949 American comedy film directed by Richard Wallace and written by Howard Dimsdale. It is a sequel to the 1945 film "Kiss and Tell".
```

#### Full Payload

```json
{
  "text": "[Consensus - Concept: sequel] (similarity: 0.75): A Kiss for Corliss is a 1949 American comedy film directed by Richard Wallace and written by Howard Dimsdale. It is a sequel to the 1945 film \"Kiss and Tell\".",
  "type": "vector_match",
  "original_obj": {
    "name": "sequel",
    "summary": "A Kiss for Corliss is a 1949 American comedy film directed by Richard Wallace and written by Howard Dimsdale. It is a sequel to the 1945 film \"Kiss and Tell\".",
    "description": null,
    "trait": null,
    "status": null,
    "entity_type": null,
    "labels": [
      "Concept",
      "Indexable"
    ],
    "score": 0.7480528354644775,
    "_source": "vector"
  },
  "is_recent": false,
  "priority": "primary",
  "vector_score": 0.7480528354644775,
  "linked_notes": [
    {
      "id": "977f7b83-a88a-4695-9dfb-49b35d4025bb",
      "content": null,
      "title": "A Kiss for Corliss",
      "created_at": "2026-02-14T22:52:01.378098+00:00"
    }
  ],
  "type_score": 0.3,
  "semantic_score": 0.7480528354644775,
  "combined_score": 0.6136369848251343,
  "domain_boost": 1.0,
  "final_score": 0.6136369848251343,
  "rerank_score": 0.0,
  "boosts": {
    "source": "vector_match",
    "domain": 1.0
  }
}
```

### Score Distribution

- Highest: `0.0000`
- Lowest: `0.0000`
- Average: `0.0000`

### Relevance Check

- `8/10` top results contain query terms (`100%`)

### Weighted Scoring Verification

- Results correctly sorted by weighted final_score (descending): `True`
- Entity-matched results: `0/8`
- Detected query entities: `['Corliss', 'Archer', 'Kiss', 'Tell']`
- Keyword-matched results: `0/8`
- Temporal query boost applied: `False`

---

## Test 3

**Query:** What science fantasy young adult series, told in first person, has a set of companion books narrating the stories of enslaved worlds and alien species?

- Retrieval Time: `10.32s`
- Total Results: `10`

### Result Breakdown

- Temporal (Recent Notes): `0`
- Graph Nodes: `0`
- Evidence (Linked Notes): `0`

### Result 1

- Type: `vector_match`
- Label: `🔗 EVIDENCE`
- Score: `0.0000`
- Is Recent: `False`

#### Full Text

```text
[Consensus - Entity: war for the oaks] (similarity: 0.76): The ‘War for the Oaks’ is a urban fantasy novel.
```

#### Full Payload

```json
{
  "text": "[Consensus - Entity: war for the oaks] (similarity: 0.76): The ‘War for the Oaks’ is a urban fantasy novel.",
  "type": "vector_match",
  "original_obj": {
    "name": "war for the oaks",
    "summary": "The ‘War for the Oaks’ is a urban fantasy novel.",
    "description": null,
    "trait": null,
    "status": null,
    "entity_type": "Book",
    "labels": [
      "Entity",
      "Indexable"
    ],
    "score": 0.756636381149292,
    "_source": "vector"
  },
  "is_recent": false,
  "priority": "primary",
  "vector_score": 0.756636381149292,
  "linked_notes": [
    {
      "id": "dc0a2cc5-b0f4-4907-ab90-7a0c28b851df",
      "content": null,
      "title": "Emma Bull",
      "created_at": "2026-02-15T06:32:49.901138+00:00"
    }
  ],
  "type_score": 1.0,
  "semantic_score": 0.756636381149292,
  "combined_score": 0.8296454668045045,
  "domain_boost": 1.0,
  "final_score": 0.8296454668045045,
  "rerank_score": 0.0,
  "boosts": {
    "source": "vector_match",
    "domain": 1.0
  }
}
```

### Result 2

- Type: `entity_match`
- Label: `🔗 EVIDENCE`
- Score: `0.0000`
- Is Recent: `False`

#### Full Text

```text
[Consensus - Concept: companion books]: Dozens of Square Enix companion books have been produced since 1998. These books focused on artwork, developer interviews, and background information on the fictional worlds and characters in Square Enix games. They did not focus on gameplay details.
```

#### Full Payload

```json
{
  "text": "[Consensus - Concept: companion books]: Dozens of Square Enix companion books have been produced since 1998. These books focused on artwork, developer interviews, and background information on the fictional worlds and characters in Square Enix games. They did not focus on gameplay details.",
  "type": "entity_match",
  "original_obj": {
    "name": "companion books",
    "labels": [
      "Concept",
      "Indexable"
    ],
    "summary": "Dozens of Square Enix companion books have been produced since 1998. These books focused on artwork, developer interviews, and background information on the fictional worlds and characters in Square Enix games. They did not focus on gameplay details.",
    "description": null,
    "trait": null,
    "status": null,
    "entity_type": null,
    "matched_query": "companion books",
    "_source": "entity_match"
  },
  "is_recent": false,
  "priority": "primary",
  "vector_score": 1.0,
  "linked_notes": [
    {
      "id": "781b95e3-7dc3-4962-9759-f5e6c8981461",
      "content": null,
      "title": "List of Square Enix companion books",
      "created_at": "2026-02-15T14:29:07.186028+00:00"
    }
  ],
  "type_score": 0.3,
  "semantic_score": 1.0,
  "combined_score": 0.79,
  "domain_boost": 1.0,
  "final_score": 0.79,
  "rerank_score": 0.0,
  "boosts": {
    "source": "entity_match",
    "domain": 1.0
  }
}
```

### Result 3

- Type: `vector_match`
- Label: `🔗 EVIDENCE`
- Score: `0.0000`
- Is Recent: `False`

#### Full Text

```text
[Consensus - Concept: science fantasy] (similarity: 0.79): Animorphs is a science fantasy series of young adult books written by Katherine Applegate and Michael Grant, published by Scholastic. It is told in first person, with six main characters narrating the books through their own perspectives.
```

#### Full Payload

```json
{
  "text": "[Consensus - Concept: science fantasy] (similarity: 0.79): Animorphs is a science fantasy series of young adult books written by Katherine Applegate and Michael Grant, published by Scholastic. It is told in first person, with six main characters narrating the books through their own perspectives.",
  "type": "vector_match",
  "original_obj": {
    "name": "science fantasy",
    "summary": "Animorphs is a science fantasy series of young adult books written by Katherine Applegate and Michael Grant, published by Scholastic. It is told in first person, with six main characters narrating the books through their own perspectives.",
    "description": null,
    "trait": null,
    "status": null,
    "entity_type": null,
    "labels": [
      "Concept",
      "Indexable"
    ],
    "score": 0.7949831485748291,
    "_source": "vector"
  },
  "is_recent": false,
  "priority": "primary",
  "vector_score": 0.7949831485748291,
  "linked_notes": [
    {
      "id": "c30b492d-9e7b-49b4-aa1d-1abe5f5e485e",
      "content": null,
      "title": "Animorphs",
      "created_at": "2026-02-14T23:13:32.480941+00:00"
    },
    {
      "id": "affd5637-7400-490c-8134-a97f81e9d85c",
      "content": null,
      "title": "Science Fantasy _magazine_",
      "created_at": "2026-02-14T19:28:55.209988+00:00"
    }
  ],
  "type_score": 0.3,
  "semantic_score": 0.7949831485748291,
  "combined_score": 0.6464882040023804,
  "domain_boost": 1.0,
  "final_score": 0.6464882040023804,
  "rerank_score": 0.0,
  "boosts": {
    "source": "vector_match",
    "domain": 1.0
  }
}
```

### Result 4

- Type: `vector_match`
- Label: `🔗 EVIDENCE`
- Score: `0.0000`
- Is Recent: `False`

#### Full Text

```text
[Consensus - Concept: alternate universe] (similarity: 0.79): The Divide trilogy is a fantasy young adult novel trilogy which takes place in an alternate universe.
```

#### Full Payload

```json
{
  "text": "[Consensus - Concept: alternate universe] (similarity: 0.79): The Divide trilogy is a fantasy young adult novel trilogy which takes place in an alternate universe.",
  "type": "vector_match",
  "original_obj": {
    "name": "alternate universe",
    "summary": "The Divide trilogy is a fantasy young adult novel trilogy which takes place in an alternate universe.",
    "description": null,
    "trait": null,
    "status": null,
    "entity_type": null,
    "labels": [
      "Concept",
      "Indexable"
    ],
    "score": 0.7931194305419922,
    "_source": "vector"
  },
  "is_recent": false,
  "priority": "primary",
  "vector_score": 0.7931194305419922,
  "linked_notes": [
    {
      "id": "c8936d05-e09e-4719-9ce6-6c3b6ec36639",
      "content": null,
      "title": "The Divide trilogy",
      "created_at": "2026-02-15T07:58:59.442804+00:00"
    }
  ],
  "type_score": 0.3,
  "semantic_score": 0.7931194305419922,
  "combined_score": 0.6451836013793946,
  "domain_boost": 1.0,
  "final_score": 0.6451836013793946,
  "rerank_score": 0.0,
  "boosts": {
    "source": "vector_match",
    "domain": 1.0
  }
}
```

### Result 5

- Type: `vector_match`
- Label: `🔗 EVIDENCE`
- Score: `0.0000`
- Is Recent: `False`

#### Full Text

```text
[Consensus - Concept: young adult books] (similarity: 0.77): Animorphs is a science fantasy series of young adult books written by Katherine Applegate and Michael Grant, writing together as K. A. Applegate. It is published by Scholastic. The series is told in first person, with six main characters narrating through their individual perspectives.
```

#### Full Payload

```json
{
  "text": "[Consensus - Concept: young adult books] (similarity: 0.77): Animorphs is a science fantasy series of young adult books written by Katherine Applegate and Michael Grant, writing together as K. A. Applegate. It is published by Scholastic. The series is told in first person, with six main characters narrating through their individual perspectives.",
  "type": "vector_match",
  "original_obj": {
    "name": "young adult books",
    "summary": "Animorphs is a science fantasy series of young adult books written by Katherine Applegate and Michael Grant, writing together as K. A. Applegate. It is published by Scholastic. The series is told in first person, with six main characters narrating through their individual perspectives.",
    "description": null,
    "trait": null,
    "status": null,
    "entity_type": null,
    "labels": [
      "Concept",
      "Indexable"
    ],
    "score": 0.7678177356719971,
    "_source": "vector"
  },
  "is_recent": false,
  "priority": "primary",
  "vector_score": 0.7678177356719971,
  "linked_notes": [
    {
      "id": "c30b492d-9e7b-49b4-aa1d-1abe5f5e485e",
      "content": null,
      "title": "Animorphs",
      "created_at": "2026-02-14T23:13:32.480941+00:00"
    }
  ],
  "type_score": 0.3,
  "semantic_score": 0.7678177356719971,
  "combined_score": 0.627472414970398,
  "domain_boost": 1.0,
  "final_score": 0.627472414970398,
  "rerank_score": 0.0,
  "boosts": {
    "source": "vector_match",
    "domain": 1.0
  }
}
```

### Result 6

- Type: `vector_match`
- Label: `🔗 EVIDENCE`
- Score: `0.0000`
- Is Recent: `False`

#### Full Text

```text
[Consensus - Concept: book series] (similarity: 0.77): Her first three books, "The Seer And The Sword", "The Healer’s Keep" and "The Light Of The Oracle" are companion books to one another.
```

#### Full Payload

```json
{
  "text": "[Consensus - Concept: book series] (similarity: 0.77): Her first three books, \"The Seer And The Sword\", \"The Healer’s Keep\" and \"The Light Of The Oracle\" are companion books to one another.",
  "type": "vector_match",
  "original_obj": {
    "name": "book series",
    "summary": "Her first three books, \"The Seer And The Sword\", \"The Healer’s Keep\" and \"The Light Of The Oracle\" are companion books to one another.",
    "description": null,
    "trait": null,
    "status": null,
    "entity_type": null,
    "labels": [
      "Concept",
      "Indexable"
    ],
    "score": 0.766444206237793,
    "_source": "vector"
  },
  "is_recent": false,
  "priority": "primary",
  "vector_score": 0.766444206237793,
  "linked_notes": [
    {
      "id": "becc3ee6-4f15-488c-a89c-26ea71a62fd2",
      "content": null,
      "title": "Victoria Hanley",
      "created_at": "2026-02-16T07:07:43.830263+00:00"
    }
  ],
  "type_score": 0.3,
  "semantic_score": 0.766444206237793,
  "combined_score": 0.626510944366455,
  "domain_boost": 1.0,
  "final_score": 0.626510944366455,
  "rerank_score": 0.0,
  "boosts": {
    "source": "vector_match",
    "domain": 1.0
  }
}
```

### Result 7

- Type: `vector_match`
- Label: `🔗 EVIDENCE`
- Score: `0.0000`
- Is Recent: `False`

#### Full Text

```text
[Consensus - Concept: animated series] (similarity: 0.75): Cartoon Network original animated series "The Marvelous Misadventures of Flapjack"
```

#### Full Payload

```json
{
  "text": "[Consensus - Concept: animated series] (similarity: 0.75): Cartoon Network original animated series \"The Marvelous Misadventures of Flapjack\"",
  "type": "vector_match",
  "original_obj": {
    "name": "animated series",
    "summary": "Cartoon Network original animated series \"The Marvelous Misadventures of Flapjack\"",
    "description": null,
    "trait": null,
    "status": null,
    "entity_type": null,
    "labels": [
      "Concept",
      "Indexable"
    ],
    "score": 0.7543540000915527,
    "_source": "vector"
  },
  "is_recent": false,
  "priority": "primary",
  "vector_score": 0.7543540000915527,
  "linked_notes": [
    {
      "id": "b7d9786a-c587-4486-95c9-4e535d41bebb",
      "content": null,
      "title": "Brian Doyle-Murray",
      "created_at": "2026-02-14T17:26:23.573081+00:00"
    }
  ],
  "type_score": 0.3,
  "semantic_score": 0.7543540000915527,
  "combined_score": 0.6180478000640869,
  "domain_boost": 1.0,
  "final_score": 0.6180478000640869,
  "rerank_score": 0.0,
  "boosts": {
    "source": "vector_match",
    "domain": 1.0
  }
}
```

### Result 8

- Type: `vector_match`
- Label: `🔗 EVIDENCE`
- Score: `0.0000`
- Is Recent: `False`

#### Full Text

```text
[Consensus - Entity: animorphs] (similarity: 0.78): Animorphs is a science fantasy series of young adult books written by Katherine Applegate and Michael Grant, writing together as K. A. Applegate. It was published by Scholastic. The series is told in first person, with six main characters narrating through their individual perspectives.
```

#### Full Payload

```json
{
  "text": "[Consensus - Entity: animorphs] (similarity: 0.78): Animorphs is a science fantasy series of young adult books written by Katherine Applegate and Michael Grant, writing together as K. A. Applegate. It was published by Scholastic. The series is told in first person, with six main characters narrating through their individual perspectives.",
  "type": "vector_match",
  "original_obj": {
    "name": "animorphs",
    "summary": "Animorphs is a science fantasy series of young adult books written by Katherine Applegate and Michael Grant, writing together as K. A. Applegate. It was published by Scholastic. The series is told in first person, with six main characters narrating through their individual perspectives.",
    "description": null,
    "trait": null,
    "status": null,
    "entity_type": "Book Series",
    "labels": [
      "Entity",
      "Indexable"
    ],
    "score": 0.7777907848358154,
    "_source": "vector"
  },
  "is_recent": false,
  "priority": "primary",
  "vector_score": 0.7777907848358154,
  "linked_notes": [
    {
      "id": "c30b492d-9e7b-49b4-aa1d-1abe5f5e485e",
      "content": null,
      "title": "Animorphs",
      "created_at": "2026-02-14T23:13:32.480941+00:00"
    }
  ],
  "type_score": 0.1,
  "semantic_score": 0.7777907848358154,
  "combined_score": 0.5744535493850709,
  "domain_boost": 1.0,
  "final_score": 0.5744535493850709,
  "rerank_score": 0.0,
  "boosts": {
    "source": "vector_match",
    "domain": 1.0
  }
}
```

### Result 9

- Type: `vector_match`
- Label: `🔗 EVIDENCE`
- Score: `0.0000`
- Is Recent: `False`

#### Full Text

```text
[Consensus - Entity: the marvelous misadventures of flapjack] (similarity: 0.75): Cartoon Network original animated series "The Marvelous Misadventures of Flapjack"
```

#### Full Payload

```json
{
  "text": "[Consensus - Entity: the marvelous misadventures of flapjack] (similarity: 0.75): Cartoon Network original animated series \"The Marvelous Misadventures of Flapjack\"",
  "type": "vector_match",
  "original_obj": {
    "name": "the marvelous misadventures of flapjack",
    "summary": "Cartoon Network original animated series \"The Marvelous Misadventures of Flapjack\"",
    "description": null,
    "trait": null,
    "status": null,
    "entity_type": "Organization",
    "labels": [
      "Entity",
      "Indexable"
    ],
    "score": 0.7543540000915527,
    "_source": "vector"
  },
  "is_recent": false,
  "priority": "primary",
  "vector_score": 0.7543540000915527,
  "linked_notes": [
    {
      "id": "b7d9786a-c587-4486-95c9-4e535d41bebb",
      "content": null,
      "title": "Brian Doyle-Murray",
      "created_at": "2026-02-14T17:26:23.573081+00:00"
    }
  ],
  "type_score": 0.1,
  "semantic_score": 0.7543540000915527,
  "combined_score": 0.5580478000640869,
  "domain_boost": 1.0,
  "final_score": 0.5580478000640869,
  "rerank_score": 0.0,
  "boosts": {
    "source": "vector_match",
    "domain": 1.0
  }
}
```

### Result 10

- Type: `vector_match`
- Label: `🔗 EVIDENCE`
- Score: `0.0000`
- Is Recent: `False`

#### Full Text

```text
[Consensus - Entity: spongebob squarepants] (similarity: 0.75): Nickelodeon animated series
```

#### Full Payload

```json
{
  "text": "[Consensus - Entity: spongebob squarepants] (similarity: 0.75): Nickelodeon animated series",
  "type": "vector_match",
  "original_obj": {
    "name": "spongebob squarepants",
    "summary": "Nickelodeon animated series",
    "description": null,
    "trait": null,
    "status": null,
    "entity_type": "Organization",
    "labels": [
      "Entity",
      "Indexable"
    ],
    "score": 0.7501249313354492,
    "_source": "vector"
  },
  "is_recent": false,
  "priority": "primary",
  "vector_score": 0.7501249313354492,
  "linked_notes": [
    {
      "id": "b7d9786a-c587-4486-95c9-4e535d41bebb",
      "content": null,
      "title": "Brian Doyle-Murray",
      "created_at": "2026-02-14T17:26:23.573081+00:00"
    }
  ],
  "type_score": 0.1,
  "semantic_score": 0.7501249313354492,
  "combined_score": 0.5550874519348145,
  "domain_boost": 1.0,
  "final_score": 0.5550874519348145,
  "rerank_score": 0.0,
  "boosts": {
    "source": "vector_match",
    "domain": 1.0
  }
}
```

### Score Distribution

- Highest: `0.0000`
- Lowest: `0.0000`
- Average: `0.0000`

### Relevance Check

- `7/10` top results contain query terms (`70%`)

### Weighted Scoring Verification

- Results correctly sorted by weighted final_score (descending): `True`
- Keyword-matched results: `0/10`
- Temporal query boost applied: `False`

---

## Test 4

**Query:** Are the Laleli Mosque and Esma Sultan Mansion located in the same neighborhood?

- Retrieval Time: `6.67s`
- Total Results: `13`

### Result Breakdown

- Temporal (Recent Notes): `0`
- Graph Nodes: `0`
- Evidence (Linked Notes): `0`

### Result 1

- Type: `entity_match`
- Label: `🔗 EVIDENCE`
- Score: `0.0000`
- Is Recent: `False`

#### Full Text

```text
[Consensus - Entity: laleli mosque]: The Laleli Mosque is an 18th-century Ottoman imperial mosque located in Laleli, Fatih, Istanbul, Turkey.
```

#### Full Payload

```json
{
  "text": "[Consensus - Entity: laleli mosque]: The Laleli Mosque is an 18th-century Ottoman imperial mosque located in Laleli, Fatih, Istanbul, Turkey.",
  "type": "entity_match",
  "original_obj": {
    "name": "laleli mosque",
    "labels": [
      "Entity",
      "Indexable"
    ],
    "summary": "The Laleli Mosque is an 18th-century Ottoman imperial mosque located in Laleli, Fatih, Istanbul, Turkey.",
    "description": null,
    "trait": null,
    "status": null,
    "entity_type": "Place",
    "matched_query": "laleli mosque",
    "_source": "entity_match"
  },
  "is_recent": false,
  "priority": "primary",
  "vector_score": 1.0,
  "linked_notes": [
    {
      "id": "137f6b69-8621-4207-a445-f350792a3f2b",
      "content": null,
      "title": "Laleli Mosque",
      "created_at": "2026-02-14T20:17:53.299077+00:00"
    }
  ],
  "type_score": 1.0,
  "semantic_score": 1.0,
  "combined_score": 1.0,
  "domain_boost": 1.0,
  "final_score": 1.0,
  "rerank_score": 0.0,
  "boosts": {
    "source": "entity_match",
    "domain": 1.0
  }
}
```

### Result 2

- Type: `entity_match`
- Label: `🔗 EVIDENCE`
- Score: `0.0000`
- Is Recent: `False`

#### Full Text

```text
[Consensus - Entity: esma sultan mansion]: The Esma Sultan Mansion is a historical yalı located in Ortaköy neighborhood of Istanbul, Turkey. It is named after its original owner, Esma Sultan. Today, it is used as a cultural center after being redeveloped.
```

#### Full Payload

```json
{
  "text": "[Consensus - Entity: esma sultan mansion]: The Esma Sultan Mansion is a historical yalı located in Ortaköy neighborhood of Istanbul, Turkey. It is named after its original owner, Esma Sultan. Today, it is used as a cultural center after being redeveloped.",
  "type": "entity_match",
  "original_obj": {
    "name": "esma sultan mansion",
    "labels": [
      "Entity",
      "Indexable"
    ],
    "summary": "The Esma Sultan Mansion is a historical yalı located in Ortaköy neighborhood of Istanbul, Turkey. It is named after its original owner, Esma Sultan. Today, it is used as a cultural center after being redeveloped.",
    "description": null,
    "trait": null,
    "status": null,
    "entity_type": "Place",
    "matched_query": "esma sultan mansion",
    "_source": "entity_match"
  },
  "is_recent": false,
  "priority": "primary",
  "vector_score": 1.0,
  "linked_notes": [
    {
      "id": "20bd9692-5f72-4624-9c78-36412bb62b55",
      "content": null,
      "title": "Esma Sultan Mansion",
      "created_at": "2026-02-15T04:41:44.980698+00:00"
    }
  ],
  "type_score": 1.0,
  "semantic_score": 1.0,
  "combined_score": 1.0,
  "domain_boost": 1.0,
  "final_score": 1.0,
  "rerank_score": 0.0,
  "boosts": {
    "source": "entity_match",
    "domain": 1.0
  }
}
```

### Result 3

- Type: `vector_match`
- Label: `🔗 EVIDENCE`
- Score: `0.0000`
- Is Recent: `False`

#### Full Text

```text
[Consensus - Entity: ortaköy] (similarity: 0.84): The Esma Sultan Mansion is a historical yalı located in Ortaköy neighborhood of Istanbul, Turkey. It was named after Esma Sultan, its original owner. Today, it is used as a cultural center after being redeveloped.
```

#### Full Payload

```json
{
  "text": "[Consensus - Entity: ortaköy] (similarity: 0.84): The Esma Sultan Mansion is a historical yalı located in Ortaköy neighborhood of Istanbul, Turkey. It was named after Esma Sultan, its original owner. Today, it is used as a cultural center after being redeveloped.",
  "type": "vector_match",
  "original_obj": {
    "name": "ortaköy",
    "summary": "The Esma Sultan Mansion is a historical yalı located in Ortaköy neighborhood of Istanbul, Turkey. It was named after Esma Sultan, its original owner. Today, it is used as a cultural center after being redeveloped.",
    "description": null,
    "trait": null,
    "status": null,
    "entity_type": "Place",
    "labels": [
      "Entity",
      "Indexable"
    ],
    "score": 0.8439924716949463,
    "_source": "vector"
  },
  "is_recent": false,
  "priority": "primary",
  "vector_score": 0.8439924716949463,
  "linked_notes": [
    {
      "id": "20bd9692-5f72-4624-9c78-36412bb62b55",
      "content": null,
      "title": "Esma Sultan Mansion",
      "created_at": "2026-02-15T04:41:44.980698+00:00"
    }
  ],
  "type_score": 1.0,
  "semantic_score": 0.8439924716949463,
  "combined_score": 0.8907947301864625,
  "domain_boost": 1.0,
  "final_score": 0.8907947301864625,
  "rerank_score": 0.0,
  "boosts": {
    "source": "vector_match",
    "domain": 1.0
  }
}
```

### Result 4

- Type: `vector_match`
- Label: `🔗 EVIDENCE`
- Score: `0.0000`
- Is Recent: `False`

#### Full Text

```text
[Consensus - Entity: istanbul] (similarity: 0.84): The Sultan Ahmed Mosque, also known as Sultan Ahmet Mosque, is a historic mosque located in Istanbul, Turkey. The Esma Sultan Mansion, a historical yalı located in Ortaköy neighborhood of Istanbul, Turkey, is used today as a cultural center.
```

#### Full Payload

```json
{
  "text": "[Consensus - Entity: istanbul] (similarity: 0.84): The Sultan Ahmed Mosque, also known as Sultan Ahmet Mosque, is a historic mosque located in Istanbul, Turkey. The Esma Sultan Mansion, a historical yalı located in Ortaköy neighborhood of Istanbul, Turkey, is used today as a cultural center.",
  "type": "vector_match",
  "original_obj": {
    "name": "istanbul",
    "summary": "The Sultan Ahmed Mosque, also known as Sultan Ahmet Mosque, is a historic mosque located in Istanbul, Turkey. The Esma Sultan Mansion, a historical yalı located in Ortaköy neighborhood of Istanbul, Turkey, is used today as a cultural center.",
    "description": null,
    "trait": null,
    "status": null,
    "entity_type": "Place",
    "labels": [
      "Entity",
      "Indexable"
    ],
    "score": 0.8390388488769531,
    "_source": "vector"
  },
  "is_recent": false,
  "priority": "primary",
  "vector_score": 0.8390388488769531,
  "linked_notes": [
    {
      "id": "20bd9692-5f72-4624-9c78-36412bb62b55",
      "content": null,
      "title": "Esma Sultan Mansion",
      "created_at": "2026-02-15T04:41:44.980698+00:00"
    },
    {
      "id": "387fa563-fde2-47cd-ada2-1ec6b94d021c",
      "content": null,
      "title": "Sultan Ahmed Mosque",
      "created_at": "2026-02-14T15:15:59.199141+00:00"
    }
  ],
  "type_score": 1.0,
  "semantic_score": 0.8390388488769531,
  "combined_score": 0.8873271942138672,
  "domain_boost": 1.0,
  "final_score": 0.8873271942138672,
  "rerank_score": 0.0,
  "boosts": {
    "source": "vector_match",
    "domain": 1.0
  }
}
```

### Result 5

- Type: `vector_match`
- Label: `🔗 EVIDENCE`
- Score: `0.0000`
- Is Recent: `False`

#### Full Text

```text
[Consensus - Entity: bosphorus] (similarity: 0.82): The Esma Sultan Mansion is located on the Bosphorus in Ortaköy neighborhood of Istanbul, Turkey. It was named after its original owner, Esma Sultan. Today, it is used as a cultural center after being redeveloped.
```

#### Full Payload

```json
{
  "text": "[Consensus - Entity: bosphorus] (similarity: 0.82): The Esma Sultan Mansion is located on the Bosphorus in Ortaköy neighborhood of Istanbul, Turkey. It was named after its original owner, Esma Sultan. Today, it is used as a cultural center after being redeveloped.",
  "type": "vector_match",
  "original_obj": {
    "name": "bosphorus",
    "summary": "The Esma Sultan Mansion is located on the Bosphorus in Ortaköy neighborhood of Istanbul, Turkey. It was named after its original owner, Esma Sultan. Today, it is used as a cultural center after being redeveloped.",
    "description": null,
    "trait": null,
    "status": null,
    "entity_type": "Place",
    "labels": [
      "Entity",
      "Indexable"
    ],
    "score": 0.8150234222412109,
    "_source": "vector"
  },
  "is_recent": false,
  "priority": "primary",
  "vector_score": 0.8150234222412109,
  "linked_notes": [
    {
      "id": "20bd9692-5f72-4624-9c78-36412bb62b55",
      "content": null,
      "title": "Esma Sultan Mansion",
      "created_at": "2026-02-15T04:41:44.980698+00:00"
    }
  ],
  "type_score": 1.0,
  "semantic_score": 0.8150234222412109,
  "combined_score": 0.8705163955688477,
  "domain_boost": 1.0,
  "final_score": 0.8705163955688477,
  "rerank_score": 0.0,
  "boosts": {
    "source": "vector_match",
    "domain": 1.0
  }
}
```

### Result 6

- Type: `vector_match`
- Label: `🔗 EVIDENCE`
- Score: `0.0000`
- Is Recent: `False`

#### Full Text

```text
[Consensus - Entity: sultan ahmed mosque] (similarity: 0.81): The Sultan Ahmed Mosque, also known as Sultan Ahmet Mosque (Turkish: "Sultan Ahmet Camii"), is located in Istanbul, Turkey. Construction took place between 1609 and 1616 during the rule of Ahmed I. The mosque features a lush red carpet, hand-painted blue tiles, five main domes, six minarets, and eight secondary domes. It is adjacent to the Hagia Sophia.
```

#### Full Payload

```json
{
  "text": "[Consensus - Entity: sultan ahmed mosque] (similarity: 0.81): The Sultan Ahmed Mosque, also known as Sultan Ahmet Mosque (Turkish: \"Sultan Ahmet Camii\"), is located in Istanbul, Turkey. Construction took place between 1609 and 1616 during the rule of Ahmed I. The mosque features a lush red carpet, hand-painted blue tiles, five main domes, six minarets, and eight secondary domes. It is adjacent to the Hagia Sophia.",
  "type": "vector_match",
  "original_obj": {
    "name": "sultan ahmed mosque",
    "summary": "The Sultan Ahmed Mosque, also known as Sultan Ahmet Mosque (Turkish: \"Sultan Ahmet Camii\"), is located in Istanbul, Turkey. Construction took place between 1609 and 1616 during the rule of Ahmed I. The mosque features a lush red carpet, hand-painted blue tiles, five main domes, six minarets, and eight secondary domes. It is adjacent to the Hagia Sophia.",
    "description": null,
    "trait": null,
    "status": null,
    "entity_type": "Place",
    "labels": [
      "Entity",
      "Indexable"
    ],
    "score": 0.8054764270782471,
    "_source": "vector"
  },
  "is_recent": false,
  "priority": "primary",
  "vector_score": 0.8054764270782471,
  "linked_notes": [
    {
      "id": "387fa563-fde2-47cd-ada2-1ec6b94d021c",
      "content": null,
      "title": "Sultan Ahmed Mosque",
      "created_at": "2026-02-14T15:15:59.199141+00:00"
    }
  ],
  "type_score": 1.0,
  "semantic_score": 0.8054764270782471,
  "combined_score": 0.863833498954773,
  "domain_boost": 1.0,
  "final_score": 0.863833498954773,
  "rerank_score": 0.0,
  "boosts": {
    "source": "vector_match",
    "domain": 1.0
  }
}
```

### Result 7

- Type: `vector_match`
- Label: `🔗 EVIDENCE`
- Score: `0.0000`
- Is Recent: `False`

#### Full Text

```text
[Consensus - Entity: algiers] (similarity: 0.75) | Connections: The Great Mosque of Algiers (Arabic: الجامع الكبير‎ ‎ , "Jemaa Kebir") is a mosque in Algiers, Algeria, located very close to Algiers Harbor.: The Great Mosque of Algiers is a mosque located in Algiers, Algeria, close to Algiers Harbor.
```

#### Full Payload

```json
{
  "text": "[Consensus - Entity: algiers] (similarity: 0.75) | Connections: The Great Mosque of Algiers (Arabic: الجامع الكبير‎ ‎ , \"Jemaa Kebir\") is a mosque in Algiers, Algeria, located very close to Algiers Harbor.: The Great Mosque of Algiers is a mosque located in Algiers, Algeria, close to Algiers Harbor.",
  "type": "vector_match",
  "original_obj": {
    "name": "algiers",
    "summary": "The Great Mosque of Algiers is a mosque located in Algiers, Algeria, close to Algiers Harbor.",
    "description": null,
    "trait": null,
    "status": null,
    "entity_type": "Place",
    "labels": [
      "Entity",
      "Indexable"
    ],
    "score": 0.7483963966369629,
    "_source": "vector"
  },
  "is_recent": false,
  "priority": "primary",
  "vector_score": 0.7483963966369629,
  "linked_notes": [
    {
      "id": "305041a4-5764-4388-9e10-86af40a53b8b",
      "content": null,
      "title": "Djamaâ el Kebir",
      "created_at": "2026-02-16T17:30:11.803762+00:00"
    }
  ],
  "type_score": 1.0,
  "semantic_score": 0.7483963966369629,
  "combined_score": 0.823877477645874,
  "domain_boost": 1.0,
  "final_score": 0.823877477645874,
  "rerank_score": 0.0,
  "boosts": {
    "source": "vector_match",
    "domain": 1.0
  }
}
```

### Result 8

- Type: `vector_match`
- Label: `🔗 EVIDENCE`
- Score: `0.0000`
- Is Recent: `False`

#### Full Text

```text
[Consensus - Entity: hagia sophia] (similarity: 0.75): It sits next to the Hagia Sophia, another popular tourist site.
```

#### Full Payload

```json
{
  "text": "[Consensus - Entity: hagia sophia] (similarity: 0.75): It sits next to the Hagia Sophia, another popular tourist site.",
  "type": "vector_match",
  "original_obj": {
    "name": "hagia sophia",
    "summary": "It sits next to the Hagia Sophia, another popular tourist site.",
    "description": null,
    "trait": null,
    "status": null,
    "entity_type": "Place",
    "labels": [
      "Entity",
      "Indexable"
    ],
    "score": 0.747089147567749,
    "_source": "vector"
  },
  "is_recent": false,
  "priority": "primary",
  "vector_score": 0.747089147567749,
  "linked_notes": [
    {
      "id": "387fa563-fde2-47cd-ada2-1ec6b94d021c",
      "content": null,
      "title": "Sultan Ahmed Mosque",
      "created_at": "2026-02-14T15:15:59.199141+00:00"
    }
  ],
  "type_score": 1.0,
  "semantic_score": 0.747089147567749,
  "combined_score": 0.8229624032974243,
  "domain_boost": 1.0,
  "final_score": 0.8229624032974243,
  "rerank_score": 0.0,
  "boosts": {
    "source": "vector_match",
    "domain": 1.0
  }
}
```

### Result 9

- Type: `vector_match`
- Label: `🔗 EVIDENCE`
- Score: `0.0000`
- Is Recent: `False`

#### Full Text

```text
[Consensus - Concept: yalı] (similarity: 0.85): The Esma Sultan Mansion, known as "Esma Sultan Yalısı", is a historical yalı (waterside mansion) located in Ortaköy neighborhood of Istanbul, Turkey. It is named after its original owner, Esma Sultan. Today, it is used as a cultural center after being redeveloped.
```

#### Full Payload

```json
{
  "text": "[Consensus - Concept: yalı] (similarity: 0.85): The Esma Sultan Mansion, known as \"Esma Sultan Yalısı\", is a historical yalı (waterside mansion) located in Ortaköy neighborhood of Istanbul, Turkey. It is named after its original owner, Esma Sultan. Today, it is used as a cultural center after being redeveloped.",
  "type": "vector_match",
  "original_obj": {
    "name": "yalı",
    "summary": "The Esma Sultan Mansion, known as \"Esma Sultan Yalısı\", is a historical yalı (waterside mansion) located in Ortaköy neighborhood of Istanbul, Turkey. It is named after its original owner, Esma Sultan. Today, it is used as a cultural center after being redeveloped.",
    "description": null,
    "trait": null,
    "status": null,
    "entity_type": null,
    "labels": [
      "Concept",
      "Indexable"
    ],
    "score": 0.8465027809143066,
    "_source": "vector"
  },
  "is_recent": false,
  "priority": "primary",
  "vector_score": 0.8465027809143066,
  "linked_notes": [
    {
      "id": "20bd9692-5f72-4624-9c78-36412bb62b55",
      "content": null,
      "title": "Esma Sultan Mansion",
      "created_at": "2026-02-15T04:41:44.980698+00:00"
    }
  ],
  "type_score": 0.3,
  "semantic_score": 0.8465027809143066,
  "combined_score": 0.6825519466400146,
  "domain_boost": 1.0,
  "final_score": 0.6825519466400146,
  "rerank_score": 0.0,
  "boosts": {
    "source": "vector_match",
    "domain": 1.0
  }
}
```

### Result 10

- Type: `vector_match`
- Label: `🔗 EVIDENCE`
- Score: `0.0000`
- Is Recent: `False`

#### Full Text

```text
[Consensus - Concept: ottoman imperial mosque] (similarity: 0.84): The Laleli Mosque is an 18th-century Ottoman imperial mosque located in Laleli, Fatih, Istanbul, Turkey.
```

#### Full Payload

```json
{
  "text": "[Consensus - Concept: ottoman imperial mosque] (similarity: 0.84): The Laleli Mosque is an 18th-century Ottoman imperial mosque located in Laleli, Fatih, Istanbul, Turkey.",
  "type": "vector_match",
  "original_obj": {
    "name": "ottoman imperial mosque",
    "summary": "The Laleli Mosque is an 18th-century Ottoman imperial mosque located in Laleli, Fatih, Istanbul, Turkey.",
    "description": null,
    "trait": null,
    "status": null,
    "entity_type": null,
    "labels": [
      "Concept",
      "Indexable"
    ],
    "score": 0.8418970108032227,
    "_source": "vector"
  },
  "is_recent": false,
  "priority": "primary",
  "vector_score": 0.8418970108032227,
  "linked_notes": [
    {
      "id": "137f6b69-8621-4207-a445-f350792a3f2b",
      "content": null,
      "title": "Laleli Mosque",
      "created_at": "2026-02-14T20:17:53.299077+00:00"
    }
  ],
  "type_score": 0.3,
  "semantic_score": 0.8418970108032227,
  "combined_score": 0.6793279075622558,
  "domain_boost": 1.0,
  "final_score": 0.6793279075622558,
  "rerank_score": 0.0,
  "boosts": {
    "source": "vector_match",
    "domain": 1.0
  }
}
```

### Result 11

- Type: `vector_match`
- Label: `🔗 EVIDENCE`
- Score: `0.0000`
- Is Recent: `False`

#### Full Text

```text
[Consensus - Concept: cultural center] (similarity: 0.84): The Esma Sultan Mansion, located in Ortaköy neighborhood of Istanbul, Turkey, is used today as a cultural center after being redeveloped. It was named after its original owner, Esma Sultan.
```

#### Full Payload

```json
{
  "text": "[Consensus - Concept: cultural center] (similarity: 0.84): The Esma Sultan Mansion, located in Ortaköy neighborhood of Istanbul, Turkey, is used today as a cultural center after being redeveloped. It was named after its original owner, Esma Sultan.",
  "type": "vector_match",
  "original_obj": {
    "name": "cultural center",
    "summary": "The Esma Sultan Mansion, located in Ortaköy neighborhood of Istanbul, Turkey, is used today as a cultural center after being redeveloped. It was named after its original owner, Esma Sultan.",
    "description": null,
    "trait": null,
    "status": null,
    "entity_type": null,
    "labels": [
      "Concept",
      "Indexable"
    ],
    "score": 0.8356227874755859,
    "_source": "vector"
  },
  "is_recent": false,
  "priority": "primary",
  "vector_score": 0.8356227874755859,
  "linked_notes": [
    {
      "id": "20bd9692-5f72-4624-9c78-36412bb62b55",
      "content": null,
      "title": "Esma Sultan Mansion",
      "created_at": "2026-02-15T04:41:44.980698+00:00"
    }
  ],
  "type_score": 0.3,
  "semantic_score": 0.8356227874755859,
  "combined_score": 0.6749359512329102,
  "domain_boost": 1.0,
  "final_score": 0.6749359512329102,
  "rerank_score": 0.0,
  "boosts": {
    "source": "vector_match",
    "domain": 1.0
  }
}
```

### Result 12

- Type: `vector_match`
- Label: `🔗 EVIDENCE`
- Score: `0.0000`
- Is Recent: `False`

#### Full Text

```text
[Consensus - Concept: mosque] (similarity: 0.78): The Sultan Ahmed Mosque (also known as the Blue Mosque) is located in Istanbul, Turkey. Construction occurred between 1609 and 1616 during the rule of Ahmed I. The mosque features a red carpet, blue tiles, five main domes, six minarets, and eight secondary domes. The Great Mosque of Algiers is located in Algiers, Algeria, and was built in 1097 under sultan Ali ibn Yusuf. Its minaret dates from 1332.
```

#### Full Payload

```json
{
  "text": "[Consensus - Concept: mosque] (similarity: 0.78): The Sultan Ahmed Mosque (also known as the Blue Mosque) is located in Istanbul, Turkey. Construction occurred between 1609 and 1616 during the rule of Ahmed I. The mosque features a red carpet, blue tiles, five main domes, six minarets, and eight secondary domes. The Great Mosque of Algiers is located in Algiers, Algeria, and was built in 1097 under sultan Ali ibn Yusuf. Its minaret dates from 1332.",
  "type": "vector_match",
  "original_obj": {
    "name": "mosque",
    "summary": "The Sultan Ahmed Mosque (also known as the Blue Mosque) is located in Istanbul, Turkey. Construction occurred between 1609 and 1616 during the rule of Ahmed I. The mosque features a red carpet, blue tiles, five main domes, six minarets, and eight secondary domes. The Great Mosque of Algiers is located in Algiers, Algeria, and was built in 1097 under sultan Ali ibn Yusuf. Its minaret dates from 1332.",
    "description": null,
    "trait": null,
    "status": null,
    "entity_type": null,
    "labels": [
      "Concept",
      "Indexable"
    ],
    "score": 0.7754952907562256,
    "_source": "vector"
  },
  "is_recent": false,
  "priority": "primary",
  "vector_score": 0.7754952907562256,
  "linked_notes": [
    {
      "id": "305041a4-5764-4388-9e10-86af40a53b8b",
      "content": null,
      "title": "Djamaâ el Kebir",
      "created_at": "2026-02-16T17:30:11.803762+00:00"
    },
    {
      "id": "387fa563-fde2-47cd-ada2-1ec6b94d021c",
      "content": null,
      "title": "Sultan Ahmed Mosque",
      "created_at": "2026-02-14T15:15:59.199141+00:00"
    }
  ],
  "type_score": 0.3,
  "semantic_score": 0.7754952907562256,
  "combined_score": 0.6328467035293579,
  "domain_boost": 1.0,
  "final_score": 0.6328467035293579,
  "rerank_score": 0.0,
  "boosts": {
    "source": "vector_match",
    "domain": 1.0
  }
}
```

### Result 13

- Type: `neighbor_node`
- Label: `🔗 EVIDENCE`
- Score: `0.0000`
- Is Recent: `False`

#### Full Text

```text
[Neighbor - Entity: djama' el kebir] (expanded from algiers): The Great Mosque of Algiers (Arabic: الجامع الكبير‎ ‎ , "Jemaa Kebir") was built in 1097. It is located near Algiers Harbor. It is known as Grand Mosque d'Alger, Djamaa al-Kebir, El Kebir Mosque and Jami Masjid. It is one of the oldest mosques in Algeria after Sidi Okba Mosque and is an example of Almoravid architecture. An inscription is on the minbar (منبر) or the pulpit.
```

#### Full Payload

```json
{
  "text": "[Neighbor - Entity: djama' el kebir] (expanded from algiers): The Great Mosque of Algiers (Arabic: الجامع الكبير‎ ‎ , \"Jemaa Kebir\") was built in 1097. It is located near Algiers Harbor. It is known as Grand Mosque d'Alger, Djamaa al-Kebir, El Kebir Mosque and Jami Masjid. It is one of the oldest mosques in Algeria after Sidi Okba Mosque and is an example of Almoravid architecture. An inscription is on the minbar (منبر) or the pulpit.",
  "type": "neighbor_node",
  "original_obj": {
    "name": "djama' el kebir",
    "label": "Entity",
    "summary": "The Great Mosque of Algiers (Arabic: الجامع الكبير‎ ‎ , \"Jemaa Kebir\") was built in 1097. It is located near Algiers Harbor. It is known as Grand Mosque d'Alger, Djamaa al-Kebir, El Kebir Mosque and Jami Masjid. It is one of the oldest mosques in Algeria after Sidi Okba Mosque and is an example of Almoravid architecture. An inscription is on the minbar (منبر) or the pulpit.",
    "description": null,
    "entity_type": "Place",
    "depth": 1,
    "relationship_path": [
      "located_in"
    ],
    "confidence_path": [
      0.95
    ],
    "context_path": [
      "The Great Mosque of Algiers (Arabic: الجامع الكبير‎ ‎ , \"Jemaa Kebir\") is a mosque in Algiers, Algeria, located very close to Algiers Harbor."
    ],
    "_source": "neighbor",
    "_expanded_from": "algiers"
  },
  "is_recent": false,
  "priority": "secondary",
  "relationship_path": [
    "located_in"
  ],
  "linked_notes": [
    {
      "id": "305041a4-5764-4388-9e10-86af40a53b8b",
      "content": null,
      "title": "Djamaâ el Kebir",
      "created_at": "2026-02-16T17:30:11.803762+00:00"
    }
  ],
  "vector_score": 0.0,
  "type_score": 1.0,
  "semantic_score": 0.4577023408767431,
  "combined_score": 0.5288511704383716,
  "domain_boost": 1.0,
  "final_score": 0.5288511704383716,
  "rerank_score": 0.0,
  "boosts": {
    "source": "neighbor_node",
    "domain": 1.0
  }
}
```

### Score Distribution

- Highest: `0.0000`
- Lowest: `0.0000`
- Average: `0.0000`

### Relevance Check

- `9/10` top results contain query terms (`90%`)

### Weighted Scoring Verification

- Results correctly sorted by weighted final_score (descending): `True`
- Entity-matched results: `0/13`
- Detected query entities: `['Laleli', 'Mosque', 'Esma', 'Sultan', 'Mansion']`
- Keyword-matched results: `0/13`
- Temporal query boost applied: `False`

---

## Overall Summary

- Average retrieval time: `9.20s`
- Total time: `36.79s`
- Average results per query: `10.8`
- Average relevance: `90%`
- Weighted scoring working: `Yes`

### Per-Query Breakdown

- Query: Were Scott Derrickson and Ed Wood of the same nationality?
  - Time: `11.86s`
  - Results: `12`
  - Relevance: `100%`
  - Distribution: `0 temporal, 0 graph, 0 evidence`
- Query: What government position was held by the woman who portrayed Corliss Archer in the film Kiss and Tell?
  - Time: `7.95s`
  - Results: `8`
  - Relevance: `100%`
  - Distribution: `0 temporal, 0 graph, 0 evidence`
- Query: What science fantasy young adult series, told in first person, has a set of companion books narrating the stories of enslaved worlds and alien species?
  - Time: `10.32s`
  - Results: `10`
  - Relevance: `70%`
  - Distribution: `0 temporal, 0 graph, 0 evidence`
- Query: Are the Laleli Mosque and Esma Sultan Mansion located in the same neighborhood?
  - Time: `6.67s`
  - Results: `13`
  - Relevance: `90%`
  - Distribution: `0 temporal, 0 graph, 0 evidence`

**Overall Assessment:** `EXCELLENT`
