# Blender API MCP Server - Full Description

## Overview

The **Blender API MCP Server** (Model Context Protocol Server) is a powerful tool that provides AI assistants with intelligent, context-aware access to the complete Blender Python API documentation. This server enables AI models to generate accurate, well-informed Blender add-on code by offering semantic search capabilities across Blender's extensive API.

**MCP Server Name**: `blender-api`

## Key Features

### 1. Semantic Search Engine
- **FAISS-powered vector search** across 8,636+ Blender API entities
- **Natural language queries** - search for concepts like "mesh subdivision" or "modal operator"
- **Intelligent ranking** based on semantic similarity using sentence-transformers
- **Sub-second response times** for instant API discovery

### 2. Rich API Documentation
- **Complete type information** from blender-stubs
- **Enhanced descriptions** from official Blender documentation
- **Parameter details** with types, defaults, and constraints
- **Return type specifications** for all methods and functions
- **Code examples** extracted from documentation

### 3. Smart Entity Relationships
- **Automatic linking** between related API components
- **Operator-to-type mappings** (e.g., `mesh.subdivide` → `Mesh`)
- **Panel-to-operator connections** for UI development
- **Inheritance hierarchies** for classes and types
- **Property relationships** showing which types contain which properties

### 4. Comprehensive Coverage
- **bpy.types** - All Blender data types (Mesh, Object, Material, etc.)
- **bpy.ops** - All operators (mesh.*, object.*, etc.)
- **bpy.props** - Property definitions (IntProperty, StringProperty, etc.)
- **bpy.utils** - Utility functions and decorators
- **UI classes** - Panels, menus, and UI elements
- **mathutils** - Vector, Matrix, and mathematical utilities

## Available MCP Tools

### 1. `search_blender_api`
Search the Blender API using natural language or technical queries.

**Parameters:**
- `query` (required): Search query (e.g., "subdivide mesh", "modal operator", "custom panel")
- `limit`: Maximum results to return (default: 10)
- `include_examples`: Include code examples in results (default: true)
- `tags`: Filter by tags like "operator", "modal", "ui", "mesh"
- `entity_types`: Filter by type ("class", "function", "operator", "property")

**Example Usage:**
```
Query: "How to create a custom panel in Blender?"
Returns: Panel classes, registration methods, example code
```

### 2. `lookup_blender_api`
Get detailed information about a specific API entity by its full path.

**Parameters:**
- `path` (required): Full API path (e.g., "bpy.types.Mesh", "bpy.ops.mesh.subdivide")
- `include_related`: Include related entities (default: true)
- `include_examples`: Include code examples (default: true)

**Example Usage:**
```
Path: "bpy.types.Panel"
Returns: Complete Panel documentation, all methods, properties, and inheritance
```

### 3. `get_blender_api_stats`
Get statistics about the indexed API coverage.

**Returns:**
- Total entity count by type
- Available tags and categories
- Index metadata
- Coverage statistics

### 4. `health_check`
Verify the server status and index availability.

## Use Cases

### 1. Blender Add-on Development
- **Accurate API usage**: Always get the correct method signatures and parameters
- **Best practices**: Learn from extracted documentation examples
- **Type safety**: Understand expected types and return values
- **UI development**: Find the right panels, operators, and properties

### 2. Learning and Exploration
- **Discover related APIs**: Find all methods that work with meshes, materials, etc.
- **Understand relationships**: See how operators connect to data types
- **Browse by category**: Explore all UI elements, all mesh operations, etc.

### 3. Code Generation
- **Precise code**: Generate code with correct API calls
- **Context awareness**: Understand which APIs work together
- **Version compatibility**: Based on Blender 3.6+ API

## Technical Implementation

### Architecture
- **FastMCP Framework**: Modern, async MCP server implementation
- **FAISS Index**: Facebook AI Similarity Search for vector operations
- **Sentence Transformers**: all-MiniLM-L6-v2 model for embeddings
- **SSE Transport**: Server-Sent Events for real-time communication

### Data Sources
- **blender-stubs**: Complete type annotations for the Blender API
- **Official documentation**: Enhanced descriptions and examples
- **Semantic analysis**: Automatic relationship discovery

### Performance
- **Index size**: ~50MB compressed
- **Query latency**: <100ms typical
- **Memory usage**: ~500MB runtime
- **Concurrent requests**: Fully async, handles multiple queries

## Integration Instructions

### For AI Assistants
When connected to this MCP server, you can:

1. **Search before coding**: Always search for the correct API before generating code
2. **Verify signatures**: Look up exact method signatures and parameters
3. **Find examples**: Request examples for complex operations
4. **Explore relationships**: Understand which APIs work together

### Example Workflow
1. User: "I want to create a custom panel with a button that subdivides the selected mesh"
2. Assistant searches: "custom panel button"
3. Assistant lookups: "bpy.types.Panel", "bpy.types.Operator"
4. Assistant searches: "subdivide mesh operator"
5. Assistant generates accurate code with proper registration

## Configuration

### Connection Details
- **Transport**: SSE (Server-Sent Events)
- **Endpoint**: `http://localhost:8080/sse/`
- **Authentication**: None required for local use

### Environment Variables
- `BLENDER_VERSION`: Target Blender version (default: 3.6)
- `EMBEDDING_MODEL`: Sentence transformer model
- `LOG_LEVEL`: Logging verbosity

## Benefits

1. **Accuracy**: No more guessing API names or parameters
2. **Completeness**: Access to the entire Blender Python API
3. **Context**: Understand relationships between different APIs
4. **Examples**: Learn from real documentation examples
5. **Speed**: Instant API discovery without manual searching
6. **Up-to-date**: Based on current Blender API structure

## Summary

The Blender API MCP Server transforms AI assistants into knowledgeable Blender developers by providing instant, intelligent access to the complete Blender Python API. Whether generating add-ons, UI panels, operators, or complex mesh manipulations, this server ensures accurate, well-informed code generation that follows Blender's API conventions and best practices.