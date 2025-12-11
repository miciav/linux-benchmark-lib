You are a **senior software engineer and software-design expert (PhD level)**.
I will give you the contents of a **single Python module** (one `.py` file).

Your task is to **analyze cohesion inside this module** and identify design problems such as:

* Low cohesion (unrelated responsibilities mixed together)
* “God classes” or “god modules” that know/do too much
* Functions or classes that change for many reasons (violating the Single Responsibility Principle)
* Hidden or implicit responsibilities that should be split

---

## What to Analyze

When you read the module, please:

1. **Identify responsibilities**

   * List the *distinct responsibilities* that the module currently has (e.g., CLI parsing, configuration, business logic, IO, logging, orchestration, data formatting, etc.).
   * For each major class and top-level function:

     * Describe what it does.
     * List the reasons it might need to change (e.g., config format changes, UI changes, plugin contracts, logging needs).

2. **Evaluate cohesion**

   * Does the module focus on **one well-defined purpose**, or is it a **grab bag** of unrelated utilities?
   * Are there classes or functions that:

     * Touch many different concerns (e.g., CLI + network + file IO + business logic)?
     * Have many unrelated dependencies injected or imported?
   * Are there “utility” functions that logically belong in other modules?

3. **Spot concrete cohesion problems**

   * Point out specific places where cohesion is poor, such as:

     * A class that handles configuration, logging, and execution.
     * A function that both parses arguments and runs complex business logic.
     * Mixed concerns like: domain logic + UI formatting + persistence in the same class/module.
   * Reference them by **name** (and briefly describe their role) so it’s clear what needs to be changed.

4. **Propose refactorings to improve cohesion**

   * Suggest how to **split the module** into more cohesive modules, or how to:

     * Extract new classes or helper modules for distinct responsibilities.
     * Move functions/classes to other existing modules where they fit better.
   * For each suggested extraction:

     * Name the new module/class (e.g., `config_loader`, `executor`, `output_formatter`).
     * Describe its single responsibility.
   * Suggest how to separate:

     * Core/domain logic from IO and infrastructure.
     * Orchestration from low-level operations.
     * UI concerns from business concerns.

5. **Check for hidden cohesion issues**

   * Are there functions that share global state or module-level variables in ways that couple unrelated features?
   * Are there big “setup” or “manager” functions that could be decomposed into smaller, more coherent steps?
   * Is there any “temporal cohesion” (functions that must be called in a specific fragile order) that could be improved with clearer abstractions?

---

## Output Format

Please structure your analysis as:

1. **Module Purpose Summary**

   * What this module is *trying* to be about.

2. **Responsibility Inventory**

   * Bullet list of the main responsibilities currently present in the module.

3. **Cohesion Problems**

   * Specific findings:

     * Which classes/functions are not cohesive and why.
     * Which responsibilities are mixed together.

4. **Refactoring Suggestions**

   * Concrete, actionable proposals:

     * What to extract into new functions/classes/modules.
     * New names and responsibilities.
     * How this would improve cohesion and maintainability.

5. **Recommended Next Steps**

   * 3–5 small refactoring steps that can be done incrementally to increase cohesion without rewriting everything.

Focus on **design and reasoning**, not on rewriting the whole file.
