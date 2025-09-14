# Query Intelligence Agent Design

## Overview

This document outlines the design and implementation plan for an LLM/agent-based query intelligence system to solve the trial-and-error problem in OPAL query development. The system will dynamically craft queries, learn from failures, and build a self-improving knowledge base.

## Problem Statement

Based on our metrics patterns documentation work, we identified a critical issue: **"A LOT of trial-and-error to get there"** when developing OPAL queries. Manual query development requires:
- Deep OPAL syntax knowledge
- Understanding of dataset schemas and field types
- Knowledge of metric types (counter, gauge, histogram, tdigest)
- Awareness of common patterns and gotchas
- Multiple iterations to get working queries

## Solution Approach: Query Intelligence Agent

### Core Concept
An intelligent agent that takes user intent, crafts OPAL queries using LLM reasoning, executes them, learns from failures, and iteratively refines until successful.

### Key Principles
1. **Dynamic Generation**: No static patterns - queries crafted fresh for each context
2. **Failure Learning**: Each error teaches the system about OPAL constraints
3. **Context Awareness**: Uses dataset/metrics intelligence for informed decisions
4. **Self-Improvement**: Successful patterns cached for future reference
5. **Iterative Refinement**: Multiple attempts with progressive improvement

## Architecture Components

### 1. Query Crafting Agent
**Purpose**: Core LLM-powered query generation engine

**Responsibilities**:
- Parse user intent and requirements
- Access dataset/metrics intelligence
- Generate contextually appropriate OPAL queries
- Apply learned patterns and avoid known failures
- Maintain conversation context across retries

**Implementation Details**:
- Uses OpenAI GPT-4 with specialized OPAL prompt engineering
- Chain-of-thought reasoning for query construction
- Access to comprehensive OPAL syntax and function documentation
- Integration with existing intelligence databases

### 2. Execution & Feedback Loop
**Purpose**: Execute queries and capture detailed failure information

**Responsibilities**:
- Execute OPAL queries via existing MCP infrastructure
- Capture and categorize error types
- Extract actionable feedback from failures
- Measure query performance and result quality

**Error Categories**:
- **Syntax Errors**: OPAL grammar violations
- **Semantic Errors**: Invalid function usage, type mismatches
- **Data Availability**: Missing fields, incorrect dataset references
- **Performance Issues**: Timeouts, resource constraints

### 3. Learning & Pattern Cache
**Purpose**: Build knowledge base from successful and failed attempts

**Responsibilities**:
- Cache successful query patterns with context
- Store failure patterns with resolution strategies
- Enable semantic search over cached patterns
- Track pattern effectiveness over time

**Database Schema**:
```sql
-- Successful query patterns
CREATE TABLE query_patterns (
    id SERIAL PRIMARY KEY,
    user_intent TEXT,
    dataset_context JSONB,
    metrics_context JSONB,
    successful_query TEXT,
    query_type VARCHAR(50),
    created_at TIMESTAMP DEFAULT NOW(),
    usage_count INTEGER DEFAULT 1,
    effectiveness_score REAL DEFAULT 1.0
);

-- Failure learning
CREATE TABLE query_failures (
    id SERIAL PRIMARY KEY,
    failed_query TEXT,
    error_type VARCHAR(50),
    error_message TEXT,
    resolution_strategy TEXT,
    context JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);
```

### 4. Intelligence Integration Layer
**Purpose**: Bridge with existing dataset and metrics intelligence

**Responsibilities**:
- Query dataset intelligence for field schemas
- Access metrics intelligence for type information
- Understand relationships between datasets
- Provide context-rich information to the agent

## Implementation Plan with OpenAI Agents SDK

### Phase 1: Foundation & SDK Setup (Week 1)
**Tasks**:
1. **OpenAI Agents SDK Setup**
   - Install and configure OpenAI Agents SDK
   - Set up API key management and authentication
   - Create basic agent structure with SDK primitives
   - Test SDK integration with simple examples

2. **Database Schema Creation**
   - Create query_intelligence database tables
   - Set up BM25 search indexes for pattern matching
   - Create stored procedures for pattern retrieval and caching

3. **Core Tools Development**
   - Implement OPAL query execution tool for agent
   - Create intelligence database query tools
   - Set up guardrails for query validation
   - Configure session management

### Phase 2: Agent Intelligence & Prompting (Week 2)
**Tasks**:
1. **Agent Instructions Development**
   - Create comprehensive OPAL syntax instructions for agent
   - Develop specialized prompts for different query types
   - Build context-aware instruction templates
   - Test agent understanding of OPAL patterns

2. **Intelligence Integration**
   - Connect agent tools to existing dataset_intelligence database
   - Connect agent tools to existing metrics_intelligence database
   - Create context enrichment functions for agent
   - Implement smart context selection based on user intent

3. **Initial Query Crafting Logic**
   - Implement agent workflow for query generation
   - Add dataset and metric type awareness to agent instructions
   - Create basic retry logic using agent sessions
   - Test with simple query patterns from our documentation

### Phase 3: Learning & Improvement (Week 3)
**Tasks**:
1. **Failure Analysis Engine**
   - Implement error categorization logic
   - Create failure pattern recognition
   - Build resolution strategy mapping

2. **Pattern Learning System**
   - Implement successful pattern caching
   - Create semantic similarity matching
   - Add pattern effectiveness tracking

3. **Iterative Refinement**
   - Advanced retry strategies based on error types
   - Chain-of-thought debugging for failures
   - Progressive query improvement logic

### Phase 4: Integration & Testing (Week 4)
**Tasks**:
1. **MCP Server Integration**
   - Add new query_intelligence tool to observe_server.py
   - Integrate with existing execute_opal_query workflow
   - Add optional automatic query suggestion on failures

2. **Testing & Validation**
   - Test with various query types and complexity levels
   - Validate against known working patterns
   - Performance testing and optimization

3. **Documentation & Deployment**
   - Create usage documentation
   - Add configuration instructions
   - Deploy to production environment

## Agentic Framework: OpenAI Agents SDK

**Selected Framework**: **OpenAI Agents SDK** (Production-ready evolution of Swarm)

### Why OpenAI Agents SDK?

Based on research from September 2024, OpenAI has released their official production-ready agentic framework:

**OpenAI Agents SDK Features**:
- **Lightweight & Minimal**: Very few abstractions, easy to understand and debug
- **Core Primitives**:
  - **Agents**: LLMs equipped with instructions and tools
  - **Handoffs**: Allow agents to delegate to other agents for specific tasks
  - **Guardrails**: Enable validation of agent inputs and outputs
  - **Sessions**: Automatically maintain conversation history across agent runs
- **Built-in Tracing**: Visualize and debug agentic flows
- **Evaluation Support**: Built-in evaluation and fine-tuning capabilities
- **Production Ready**: Actively maintained by OpenAI team

### Key Advantages for Our Use Case

1. **Native OpenAI Integration**: Seamless integration with OpenAI models and APIs
2. **Conversation Memory**: Built-in session management for retry logic
3. **Tool Integration**: Natural integration with our OPAL query execution tools
4. **Guardrails**: Input/output validation perfect for query syntax checking
5. **Tracing**: Debug failed queries and understand agent decision-making
6. **Official Support**: Production-ready with ongoing OpenAI maintenance

### Architecture Mapping

Our Query Intelligence Agent maps perfectly to the SDK primitives:

- **Main Agent**: OPAL Query Crafting Agent with specialized instructions
- **Tools**: Integration with `execute_opal_query` and intelligence databases
- **Sessions**: Maintain context across query retry iterations
- **Guardrails**: Validate generated queries before execution
- **Handoffs**: Future expansion to specialized agents (metrics, logs, traces)

## Technical Requirements

### Dependencies
```python
# OpenAI Agents SDK (primary framework)
openai-agents>=1.0.0  # Official OpenAI Agents SDK
openai>=1.0.0

# Database connectivity
psycopg2-binary>=2.9.0
sqlalchemy>=2.0.0

# For pattern matching and similarity (if needed)
sentence-transformers>=2.2.0  # For semantic pattern matching
numpy>=1.24.0

# For async operations (SDK supports async)
asyncio
aiohttp>=3.8.0

# For configuration and validation
python-dotenv>=1.0.0
pydantic>=2.0.0
```

### Environment Configuration
```env
# OpenAI API (required for Agents SDK)
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-5  # Latest model recommended for agents

# Query Intelligence Agent Configuration
QUERY_INTELLIGENCE_MAX_RETRIES=5
QUERY_INTELLIGENCE_TIMEOUT=60
QUERY_INTELLIGENCE_CACHE_SIZE=1000
QUERY_INTELLIGENCE_SESSION_TTL=3600  # Session timeout in seconds

# OpenAI Agents SDK Configuration
OPENAI_AGENTS_TRACE_ENABLED=true  # Enable built-in tracing
OPENAI_AGENTS_GUARDRAILS_ENABLED=true  # Enable input/output validation

# Logging
QUERY_INTELLIGENCE_LOG_LEVEL=INFO
```

### File Structure
```
scripts/
├── query_intelligence.py          # Main CLI entry point
├── query_agent/
│   ├── __init__.py
│   ├── agent.py                   # OpenAI Agents SDK integration
│   ├── tools.py                   # OPAL execution and intelligence tools
│   ├── prompts.py                 # Agent instructions and prompts
│   ├── guardrails.py              # Input/output validation
│   ├── session.py                 # Session and memory management
│   ├── cache.py                   # Pattern learning and caching
│   └── intelligence.py           # Dataset/metrics context integration
└── tests/
    ├── test_query_agent.py
    ├── test_tools.py
    ├── test_guardrails.py
    └── fixtures/
        ├── sample_sessions.json
        ├── sample_queries.json
        └── sample_errors.json

sql/
└── query_intelligence_schema.sql  # Database schema for pattern cache

docs/
└── Query Intelligence Agent Design.md  # This document
```

## OpenAI Agents SDK Implementation Example

### Core Agent Structure
```python
from openai_agents import Agent, Tool, Guardrail, Session
from typing import List, Dict, Any
import logging

class QueryIntelligenceAgent:
    def __init__(self, openai_api_key: str, database_config: Dict[str, Any]):
        self.agent = Agent(
            name="OPAL Query Intelligence Agent",
            instructions=self._load_opal_instructions(),
            model="gpt-4o",
            tools=[
                self._create_opal_execution_tool(),
                self._create_dataset_intelligence_tool(),
                self._create_metrics_intelligence_tool(),
                self._create_pattern_cache_tool()
            ],
            guardrails=[
                self._create_query_validation_guardrail(),
                self._create_output_safety_guardrail()
            ]
        )

    def _load_opal_instructions(self) -> str:
        return """
        You are an expert OPAL query crafting agent for Observe platform.

        Your role:
        1. Understand user intent for data analysis
        2. Generate syntactically correct and efficient OPAL queries
        3. Learn from failures and improve query generation
        4. Use available intelligence about datasets and metrics

        OPAL Syntax Rules:
        - Use m("metric_name") for regular metrics
        - Use m_tdigest("metric_name") for TDigest metrics
        - Always use align → aggregate pattern for time-series
        - Filter early in pipeline for performance
        - Convert units appropriately (ns to ms, bytes to GB)

        Available Tools:
        - execute_opal_query: Execute OPAL queries and get results/errors
        - get_dataset_intelligence: Get dataset schema and field information
        - get_metrics_intelligence: Get metric types and usage patterns
        - cache_successful_pattern: Store working query patterns
        """

    def _create_opal_execution_tool(self) -> Tool:
        return Tool(
            name="execute_opal_query",
            description="Execute an OPAL query against Observe datasets",
            function=self._execute_opal_query
        )

    def _create_query_validation_guardrail(self) -> Guardrail:
        return Guardrail(
            name="query_syntax_validator",
            validate_input=True,
            validate_output=True,
            validation_function=self._validate_opal_syntax
        )

    async def craft_query(self, user_intent: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Main entry point for query crafting with retry logic"""
        session = Session(
            agent=self.agent,
            context=context,
            max_turns=5  # Allow up to 5 retry attempts
        )

        result = await session.run(
            message=f"Create an OPAL query for: {user_intent}",
            context=context
        )

        return {
            "query": result.final_query,
            "success": result.success,
            "attempts": result.turn_count,
            "trace": result.trace_data
        }
```

### Tool Integration Example
```python
def _execute_opal_query(self, query: str, dataset_id: str, **kwargs) -> Dict[str, Any]:
    """Execute OPAL query and return results or detailed error information"""
    try:
        # Use existing MCP infrastructure
        result = execute_opal_query(
            query=query,
            primary_dataset_id=dataset_id,
            time_range="1h"
        )

        # Cache successful pattern
        self._cache_successful_query(query, dataset_id, result)

        return {
            "success": True,
            "data": result,
            "query": query
        }

    except Exception as error:
        # Detailed error analysis for agent learning
        error_analysis = self._analyze_opal_error(str(error), query)

        return {
            "success": False,
            "error": str(error),
            "error_type": error_analysis["type"],
            "suggestion": error_analysis["suggestion"],
            "query": query
        }

def _analyze_opal_error(self, error_message: str, query: str) -> Dict[str, Any]:
    """Analyze OPAL errors and provide actionable feedback"""
    if "syntax error" in error_message.lower():
        return {
            "type": "syntax",
            "suggestion": "Check OPAL syntax - ensure proper function usage and operators"
        }
    elif "metric not found" in error_message.lower():
        return {
            "type": "missing_metric",
            "suggestion": "Verify metric name exists in dataset using metrics intelligence"
        }
    elif "field not found" in error_message.lower():
        return {
            "type": "missing_field",
            "suggestion": "Check available fields using dataset intelligence"
        }
    else:
        return {
            "type": "unknown",
            "suggestion": "Review query logic and dataset compatibility"
        }
```

### Session Management
```python
class QuerySession:
    """Manages conversation context and retry logic using SDK sessions"""

    def __init__(self, agent: Agent, user_intent: str):
        self.session = Session(
            agent=agent,
            context={
                "user_intent": user_intent,
                "attempt_history": [],
                "learned_patterns": []
            }
        )

    async def iterative_query_crafting(self) -> Dict[str, Any]:
        """Implement iterative refinement with agent sessions"""
        max_attempts = 5

        for attempt in range(max_attempts):
            try:
                # Agent crafts query based on context and previous attempts
                response = await self.session.run(
                    message=f"Attempt {attempt + 1}: Generate OPAL query",
                    context={
                        "previous_failures": self.session.context["attempt_history"],
                        "available_intelligence": await self._gather_intelligence()
                    }
                )

                # If successful, return result
                if response.success:
                    return {
                        "success": True,
                        "query": response.query,
                        "attempts": attempt + 1,
                        "trace": response.trace
                    }

                # Record failure for next attempt
                self.session.context["attempt_history"].append({
                    "attempt": attempt + 1,
                    "query": response.query,
                    "error": response.error,
                    "learned": response.learning_points
                })

            except Exception as e:
                logging.error(f"Attempt {attempt + 1} failed: {e}")

        return {
            "success": False,
            "error": "Max attempts reached without success",
            "attempts": max_attempts,
            "history": self.session.context["attempt_history"]
        }
```

## Success Metrics

### Quantitative Metrics
1. **Query Success Rate**: % of user intents successfully translated to working OPAL queries
2. **Iteration Reduction**: Average number of attempts needed (target: <3)
3. **Time to Success**: Average time from intent to working query (target: <30s)
4. **Pattern Reuse**: % of queries that benefit from cached patterns
5. **Error Reduction**: Decrease in common error types over time

### Qualitative Metrics
1. **User Satisfaction**: Feedback on query quality and relevance
2. **Query Complexity**: Ability to handle advanced OPAL patterns
3. **Context Understanding**: Accuracy of dataset and metric interpretation
4. **Learning Effectiveness**: Improvement in success rate over time

## Risk Assessment & Mitigation

### Technical Risks
1. **OpenAI API Costs**: Potential high usage costs
   - *Mitigation*: Implement query caching, use efficient models, set usage limits

2. **Query Quality**: Generated queries may be inefficient or incorrect
   - *Mitigation*: Extensive testing, validation against known patterns, performance monitoring

3. **Error Handling**: Complex OPAL errors may be difficult to parse
   - *Mitigation*: Comprehensive error categorization, human-in-the-loop fallback

### Operational Risks
1. **API Dependencies**: Reliance on external OpenAI service
   - *Mitigation*: Local model fallback option, graceful degradation

2. **Database Growth**: Pattern cache may grow large over time
   - *Mitigation*: Implement cache cleanup, pattern effectiveness scoring

## Future Enhancements

### Advanced Features
1. **Multi-Dataset Joins**: Intelligent query generation across multiple datasets
2. **Query Optimization**: Automatic performance tuning suggestions
3. **Natural Language Interface**: Conversational query building
4. **Query Explanation**: Natural language explanation of generated queries

### Integration Opportunities
1. **Dashboard Integration**: Direct integration with Observe dashboard query builder
2. **Slack Bot**: Query assistance via Slack commands
3. **VS Code Extension**: IDE integration for query development
4. **API Endpoints**: RESTful API for external integrations

## Next Steps

1. **Immediate**: Review and approve this design document
2. **Setup**: Configure OpenAI API key and choose agentic framework
3. **Phase 1 Start**: Begin database schema creation and basic agent structure
4. **Regular Reviews**: Weekly progress reviews and design iteration

---

*Document Version: 1.0*
*Last Updated: September 14, 2024*
*Authors: Max & Claude*