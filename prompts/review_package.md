You are a **senior software engineer and software-design expert (PhD level)**.
I will give you the contents of a **Python package** (a directory containing multiple `.py` files).

Your task is to **analyze cohesion inside this package** and identify design problems such as:

* Low cohesion (the package groups unrelated responsibilities)
* “God packages” or subpackages that contain too many different concerns
* Modules or classes inside the package that violate the Single Responsibility Principle
* Hidden or implicit responsibilities that should be split across clearer subpackages

---

## What to Analyze

When you read the package, please:

1. **Identify the package’s actual responsibilities**

   * List the *distinct responsibilities* currently implemented across the package.
   * For each module, class, and major function inside the package:

     * Describe its purpose.
     * List the likely reasons it may need to change.

2. **Evaluate cohesion at the package level**

   * Does the package have a **single, well-defined purpose**, or does it mix:

     * UI concerns
     * orchestration or workflow logic
     * low-level execution or I/O
     * configuration handling
     * domain logic
     * utilities
   * Are submodules tightly and meaningfully related, or artificially grouped together?

3. **Spot concrete cohesion problems**

   * Identify modules inside the package that:

     * Contain heterogeneous concerns
     * Use unrelated dependencies
     * Act as “god modules” for several parts of the system
   * Identify cases where:

     * A module handles both IO and business logic
     * A module mixes Runner logic with Controller/UI concerns
     * Helper utilities inside the package have nothing to do with its core purpose

   Reference modules/classes by **name** so the issues are clear.

4. **Propose refactorings to improve cohesion**

   * Suggest how to reorganize the package:

     * Splitting it into multiple smaller, cohesive packages
     * Extracting new modules for distinct concerns (e.g., `config`, `executor`, `formatters`, `api`, etc.)
     * Moving functions/classes to other existing packages where they logically belong
   * For each extraction/reorganization:

     * Propose the new package/module name
     * Clearly define its single responsibility
     * Explain how this improves cohesion, readability, and maintainability

5. **Check for hidden cohesion issues**

   * Identify:

     * Temporal cohesion (ordering dependencies between modules)
     * Global state or shared variables that couple unrelated features
     * Modules that import each other circularly because responsibilities are blurred
   * Highlight any signs that the package is doing too many jobs at once.

---

## Output Format

Please structure your analysis as:

1. **Package Purpose Summary**

   * What this package *appears* to be about.
   * Whether its actual contents match its intended role.

2. **Responsibility Inventory**

   * Bullet list of the main responsibilities present in the package (even the unintended ones).

3. **Cohesion Problems**

   * Detailed findings:

     * Which modules/classes are not cohesive and why.
     * Which parts of the package mix unrelated concerns.

4. **Refactoring Suggestions**

   * Specific, actionable proposals:

     * What should be split, extracted, moved, or renamed.
     * New package/module boundaries and names.
     * Justification of architectural benefits.

5. **Recommended Next Steps**

   * 3–5 incremental refactoring steps to improve cohesion without breaking the system.

Focus on **design, reasoning, structure, and package-level cohesion**, not on rewriting the code.
