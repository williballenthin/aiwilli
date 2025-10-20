# IDA Pro Domain API Index

This index provides an overview of the IDA Pro Domain API sections to help you find the right routines for your reverse engineering tasks.

## Bytes

The Bytes API provides low-level memory and data manipulation capabilities within the IDA database. This section allows you to read and write raw bytes at specific memory addresses, check byte flags and data types, and search for binary patterns or text. Use this section when you need to analyze raw memory contents, modify binary data directly, or search for specific byte sequences in the analyzed program.

**Documentation:** https://ida-domain.docs.hex-rays.com/ref/bytes/

## Comments

The Comments API manages all comment operations within the IDA database, supporting both regular and repeatable comments. This section provides functions to add, delete, and retrieve comments associated with specific memory addresses or code locations. Use this section when you need to annotate your reverse engineering findings, add contextual information to specific code locations, or systematically manage documentation within your analysis.

**Documentation:** https://ida-domain.docs.hex-rays.com/ref/comments/

## Database

The Database API manages overall database operations and provides access to high-level database functionality. This section handles opening and closing databases, accessing database metadata, and configuring global analysis options. Use this section when you need to programmatically load binary files for analysis, manage the database lifecycle, or retrieve comprehensive information about the currently analyzed program.

**Documentation:** https://ida-domain.docs.hex-rays.com/ref/database/

## Entries

The Entries API focuses on managing and analyzing program entry points within the binary. This section provides functions to list all program entry points and retrieve detailed metadata about each entry location. Use this section when you need to identify where program execution begins, analyze program initialization sequences, or understand multiple entry points in complex binaries.

**Documentation:** https://ida-domain.docs.hex-rays.com/ref/entries/

## Flowchart

The Flowchart API enables control flow analysis and visualization of program execution paths. This section generates control flow graphs, analyzes basic blocks, and helps understand the logical structure of functions and programs. Use this section when you need to visualize function control flow, identify complex code structures, or perform static analysis of program execution paths.

**Documentation:** https://ida-domain.docs.hex-rays.com/ref/flowchart/

## Functions

The Functions API provides comprehensive function analysis and manipulation capabilities. This section allows you to list and iterate through all functions, retrieve detailed function metadata, analyze local variables, and extract function signatures. Use this section when you need to identify and understand program functions, analyze function call relationships, or extract detailed information about function implementations.

**Documentation:** https://ida-domain.docs.hex-rays.com/ref/functions/

## Heads

The Heads API provides iteration capabilities over defined items in the IDA database, including instructions and data items. This section enables systematic traversal of all analyzed elements within specified address ranges. Use this section when you need to iterate through all defined items in a program, perform batch operations on multiple addresses, or systematically analyze large portions of code or data.

**Documentation:** https://ida-domain.docs.hex-rays.com/ref/heads/

## Hooks

The Hooks API enables event-driven programming by intercepting and handling various IDA events. This section allows you to register custom event handlers for database changes, UI interactions, and processor events. Use this section when you need to implement custom analysis workflows, create interactive analysis tools, or monitor and log specific events during your reverse engineering process.

**Documentation:** https://ida-domain.docs.hex-rays.com/ref/hooks/

## Instructions

The Instructions API provides detailed low-level instruction analysis and disassembly capabilities. This section retrieves instruction details, generates human-readable disassembly, and analyzes instruction properties and operands. Use this section when you need to perform detailed instruction-level analysis, extract disassembly programmatically, or analyze specific instruction characteristics and behaviors.

**Documentation:** https://ida-domain.docs.hex-rays.com/ref/instructions/

## Names

The Names API manages symbol names and identifiers throughout the IDA database. This section handles naming of functions, variables, and memory locations, as well as retrieving and manipulating existing names. Use this section when you need to programmatically assign meaningful names to discovered functions and data, search for specific named entities, or manage symbol information systematically.

**Documentation:** https://ida-domain.docs.hex-rays.com/ref/names/

## Operands

The Operands API provides detailed analysis of instruction operands and their properties. This section analyzes operand types, values, and references, helping understand how instructions interact with data and memory. Use this section when you need to analyze instruction arguments, understand data flow between instructions, or examine how specific operands are used throughout the program.

**Documentation:** https://ida-domain.docs.hex-rays.com/ref/operands/

## Segments

The Segments API manages memory segments and sections within the analyzed binary. This section provides access to segment information, boundaries, and properties, helping understand the memory layout of the analyzed program. Use this section when you need to analyze memory organization, understand segment boundaries and permissions, or work with specific sections of the binary file.

**Documentation:** https://ida-domain.docs.hex-rays.com/ref/segments/

## Signature Files

The Signature Files API manages FLIRT (Fast Library Identification and Recognition Technology) signatures for library function identification. This section handles loading signature files and applying them to identify known library functions automatically. Use this section when you need to identify standard library functions, apply custom signatures, or improve the automatic analysis of library code in your binaries.

**Documentation:** https://ida-domain.docs.hex-rays.com/ref/signature_files/

## Strings

The Strings API provides comprehensive string analysis and management capabilities within the IDA database. This section identifies, retrieves, and analyzes string literals found throughout the analyzed program. Use this section when you need to extract all strings from a binary, search for specific string patterns, or analyze how strings are used throughout the program for configuration, debugging, or functionality purposes.

**Documentation:** https://ida-domain.docs.hex-rays.com/ref/strings/

## Types

The Types API manages type information, structures, and data type definitions within IDA. This section handles creation, modification, and application of custom data types, structures, and type libraries. Use this section when you need to define custom data structures, apply type information to improve analysis, or work with complex data types that enhance the understanding of the analyzed program.

**Documentation:** https://ida-domain.docs.hex-rays.com/ref/types/

## Xrefs

The Xrefs (Cross-references) API provides analysis of relationships between different parts of the program. This section identifies and analyzes references between functions, data, and code locations, helping understand program connectivity and data flow. Use this section when you need to trace how functions are called, identify data usage patterns, or understand the relationships between different parts of the analyzed program.

**Documentation:** https://ida-domain.docs.hex-rays.com/ref/xrefs/