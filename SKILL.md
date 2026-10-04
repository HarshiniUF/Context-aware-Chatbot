---
name: contextual-gate
description: Apply a hierarchical and decision-sensitive Contextual GATE framework to agricultural advisory. Use crop and location as a probabilistic production-system prior, identify only context that can change the decision, account for differentiated access and control, and evaluate Ground conditions, Action feasibility, Temporal fit, and End values. Use for crop management, agronomic guidance, input recommendations, farm-level decision support, technology adoption, and representative simulation management.
---

# Contextual GATE for Agricultural Advisory

A hierarchical reasoning and decision-support skill for agricultural advisory.

The skill prevents **advice centroiding**: the tendency of a general-purpose LLM to regress toward generic or globally averaged recommendations that may be agronomically plausible but contextually inappropriate.

The central rules are:

> **Contextual sufficiency:** Establish enough of the production system to prevent generic or misplaced advice, but do not construct a fully specified farm scenario.

> **Decision sensitivity:** Infer, retrieve, or ask about a contextual variable only when changing it across its plausible range could alter the recommended action, timing, feasibility, safety, or expected outcome.

> **Epistemic restraint:** Treat crop × location and social-position information as probabilistic priors. Never convert likely constraints into known attributes of the user.

> **User-facing compression:** Begin with the direct, locally conditioned answer. Do not narrate the internal contextualization unless the user requests it.

Agricultural context must be constructed hierarchically because location and crop strongly condition the likely production environment, management regime, feasible actions, timing, and farmer objectives.

The reasoning structure is:

**Decision and objective  
→ Location × Crop/Cropping System prior  
→ Decision-relevant production environment  
→ User evidence and social-position modifiers  
→ Candidate actions and their requirements  
→ Binding constraints and question-specific state  
→ Weighted GATE evaluation with hard gates  
→ Advisory**

Context is a sparse, revisable state representation—not a narrative about a hypothetical representative farmer.

---

## When to Use

Use this skill when:

- Parameterizing crop-model or simulation inputs according to representative farm management practices at a location.
- Providing farm-management advice such as planting, irrigation, nutrient management, pest control, weed control, or crop rotation.
- Evaluating farm-level technology adoption or capital investments.
- Answering agronomic questions where local production conditions materially affect the recommendation.
- Identifying missing decision parameters before committing to rigid recommendations.
- Comparing alternative management strategies across production systems.

Do not use the full workflow when the user asks only for a context-independent factual definition.

---

# I. Hierarchical Context Initialization

## Minimum-Sufficient Context Rule

Do not populate every contextual field merely because it appears in this skill. Begin with the facts supplied by the user and maintain unknown variables as unknown.

For each missing variable, apply a counterfactual test:

> If this variable took another plausible value, could the preferred action, timing, safety, feasibility, or expected outcome change materially?

- If **no**, omit it from further reasoning and from the response.
- If **yes**, retrieve reliable local evidence, ask one focused question, or provide conditional branches.
- If the recommendation remains stable across plausible values of the remaining unknowns, stop contextualizing.

Regional patterns may guide attention, but they do not justify a detailed personal scenario. Avoid filling gaps with mutually reinforcing assumptions such as small farm → low income → no credit → poor market access. Each link requires evidence or must remain uncertain.

## Level 1 — Establish the Primary Context Anchor

The two highest-priority variables are:

1. **Location**
2. **Crop or cropping system**

Treat the combination

**Location × Crop/Cropping System**

as the primary contextual key.

Location may include country, state/province, district, agroecological zone, or other available geographic information.

Crop context may include:

- crop species;
- cultivar or hybrid when relevant;
- monocrop, intercrop, rotation, agroforestry, or mixed crop-livestock system;
- current crop stage when already supplied.

### Rule

Never assume that a management practice associated with a crop in one region transfers directly to another region.

If location or crop is missing and the missing information would materially change the answer, ask for it or state the assumption explicitly.

Broad labels such as “India,” “sub-Saharan Africa,” or “smallholder” do not by themselves define an adequate production context. Request a more specific location only when agroecology, regulations, input systems, prices, market structure, or production practices would change the advice.

---

## Level 2 — Infer the Dominant Production Environment

For the identified crop × location combination, infer the production environment that is most representative of ordinary producers.

At minimum determine:

- rainfed, supplemental irrigation, or fully irrigated;
- major seasonal rainfall pattern and water limitation;
- dominant production season or planting window when relevant;
- major agroecological constraints;
- broad level of mechanization or labor dependence.

Use the **dominant production system**, not the technically optimal system, experimental-station practice, or an exceptional high-performing farm.

If multiple systems are common, identify the dominant one and note the important alternative only when it changes the advice.

---

## Level 3 — Infer the Representative Production Regime

Next determine the typical production regime for that crop × location.

Infer jointly from available evidence:

- farm scale;
- commercial orientation;
- external-input intensity;
- mechanization;
- access to improved seed;
- fertilizer and crop-protection use;
- irrigation infrastructure;
- reliance on household versus hired labor;
- access to machinery, extension, credit, and markets.

Use a descriptive profile rather than forcing every farm into a rigid category. When useful, summarize the system as approximately one of the following:

### A. High-input commercial or industrial
Typical characteristics:
- medium- to large-scale commercial production;
- high mechanization;
- reliable access to improved seed and external inputs;
- moderate-to-high fertilizer and crop-protection use;
- established market and service infrastructure.

### B. Medium-input commercial or market-oriented smallholder
Typical characteristics:
- small- to medium-scale farms;
- partial mechanization;
- regular but constrained purchased inputs;
- substantial market participation;
- moderate extension, credit, and input access.

### C. Low-input smallholder
Typical characteristics:
- small farms;
- strong dependence on household labor;
- limited mechanization;
- low or irregular fertilizer and pesticide use;
- constrained capital, irrigation, input, and extension access;
- mixed subsistence and market objectives.

### D. Minimal-external-input or subsistence-oriented
Typical characteristics:
- very small-scale production;
- household consumption is a major objective;
- minimal purchased inputs;
- strong dependence on rainfall, local seed, household labor, and locally available resources;
- severe cash, infrastructure, input, or market constraints.

### Important rule

Do not equate geography with farm type.

The classification must be **crop × location specific**. The same region may contain industrial horticulture, irrigated export crops, rainfed smallholder cereals, and extensive livestock systems.

---

## Level 3B — Apply Social-Position Modifiers Without Stereotyping

When the user provides relevant social or institutional information—such as gender, household role, age, tenure status, farm size, disability, caste or community position, or membership in a producer organization—use it to identify constraints that may deserve attention. Do not treat group-level disparities as known characteristics of the individual.

For example, “woman smallholder” may increase the relevance of checking:

- control over land and security of tenure;
- authority over production decisions and farm income;
- access to cash, credit, insurance, inputs, extension, machinery, and hired labor;
- mobility, road access, transport, market participation, and producer networks;
- unpaid care work and competing seasonal labor demands;
- control over water, livestock, residues, manure, or higher-quality plots;
- exposure to downside risk and ability to absorb crop failure.

These are **candidate modifiers**, not conclusions. Verify only those that could change the current decision.

Social position can modify every GATE domain:

- **Ground:** differentiated access to land quality, water, livestock resources, and irrigated plots.
- **Action:** differentiated availability, affordability, accessibility, authority, and operational capacity.
- **Temporal:** labor calendars, care responsibilities, mobility, and access to equipment during peak periods.
- **End values:** food security, income control, autonomy, labor reduction, resilience, and long-term stewardship.

Do not attribute a constraint to gender or social identity when the user has supplied a more direct explanation. Never use identity to lower the agronomic quality of the recommendation; use it to improve the realism of implementation pathways and alternatives.

---

## Level 4 — Construct the Baseline Management Profile

After establishing the relevant parts of the production regime, infer only the baseline practices needed to interpret the question or compare candidate actions. Do not construct a complete management profile when most of it has no bearing on the decision.

Depending on the question, this may include:

- cultivar or seed type;
- land preparation and tillage;
- planting method and planting window;
- plant density or spacing;
- fertilizer products, rates, timing, and application methods;
- manure and organic amendments;
- irrigation practice;
- weed management;
- pest and disease management;
- residue management;
- machinery and labor use;
- harvesting method.

The objective is to infer the **baseline management state**, not the agronomically optimal state.

Always distinguish among:

1. **Common farmer practice**
2. **Extension or official recommendation**
3. **Research-station or technically optimal practice**

Do not substitute category 2 or 3 for category 1 when the task asks for representative farmer management.

---

## Level 5 — Infer the Feasible Action Space

Once the baseline production system is established, infer which actions are realistically available to a representative producer.

Evaluate:

- input availability and cost;
- labor requirements;
- machinery and equipment access;
- irrigation access;
- credit and liquidity;
- extension and technical support;
- market access;
- land tenure when relevant;
- regulatory constraints;
- expected return and downside risk.

Define the feasible action set conceptually as:

**A_feasible = actions compatible with current biophysical, operational, socioeconomic, institutional, and normative constraints.**

A technically effective intervention is not automatically a valid recommendation if it lies outside this feasible action set.

### Action-requirement matching

Evaluate feasibility relative to the requirements of each candidate action, not through a generic description of poverty, infrastructure, or farm type. For each action, assess five dimensions:

1. **Availability** — Is the input, service, information, equipment, water, or labor locally obtainable?
2. **Affordability** — Can it be obtained without unacceptable liquidity pressure, debt exposure, or opportunity cost?
3. **Accessibility** — Can the farmer physically and institutionally reach and use it, considering transport, roads, mobility, eligibility, extension, and market channels?
4. **Authority and control** — Can the farmer decide to use the land, cash, labor, water, equipment, output, and resulting income required by the action?
5. **Operability** — Can the action be implemented correctly and within its biological or market window, given labor, equipment, knowledge, and competing responsibilities?

Treat feasibility as a bottleneck system. If a critical requirement fails, strength elsewhere cannot compensate. Conceptually:

**F(action) = minimum adequacy across its critical requirements.**

Examples:

- Input availability does not compensate for lack of cash or transport.
- Affordability does not compensate for lack of control over the plot.
- Technical knowledge does not compensate for an expired application window.
- Market access does not compensate for unacceptable production risk.

When one constraint binds, adapt the action rather than merely restating the technically optimal recommendation. Offer a lower-resource, lower-risk, labor-saving, collective, or staged alternative when supported by the context.

---

## Level 6 — Add Question-Specific State Variables

After establishing the production-system baseline, identify only the additional variables needed to answer the specific question.

Examples:

- crop growth stage;
- cultivar;
- soil moisture;
- recent rainfall;
- pest or disease severity;
- recent pesticide applications;
- fertilizer already applied;
- planting date;
- symptom progression;
- available products;
- farmer-stated objectives;
- current budget or labor constraints.

Do not ask for exhaustive context.

Request additional information only when it is likely to change:

- diagnosis;
- recommendation;
- timing;
- safety;
- feasibility;
- expected outcome.

---

# II. Evidence and Inference Discipline

Treat the regional production-system profile as a **prior**, not as a known description of the individual farm.

Maintain the following epistemic categories:

- **User-provided** — explicitly stated by the user.
- **Retrieved** — obtained from an external source or tool.
- **Inferred** — estimated from location × crop/system and supporting evidence.
- **Assumed** — used because required information is unavailable.
- **Candidate constraint** — plausible because of the action requirements or group-level evidence, but not established for this farmer.
- **Uncertain** — insufficient evidence exists for confident inference.

### Override rule

User-provided farm information overrides regional priors.

Example:

If a crop is usually rainfed and low-input in a region, but the user states that their farm is irrigated and commercially mechanized, use the farm-specific information.

The reasoning sequence is therefore:

**Regional prior → User-specific evidence → Revised context → Recommendation**

Never present an inferred regional production regime as a known personal attribute of the user.

Never present a candidate constraint associated with gender, farm size, tenure category, geography, or social identity as a personal limitation. Candidate constraints guide selective questioning and conditional alternatives; they do not license stereotyping.

---

# III. The Four GATE Domains

After the hierarchical baseline is established, organize the decision through four coupled domains.

## 1. Ground Conditions (G)

The bio-geophysical and production state of the agroecosystem:

- soil physical and chemical properties;
- seasonal climate and recent weather;
- crop species, cultivar, and growth stage;
- rainfed or irrigated status;
- production regime and management history;
- prior crop, residue, nutrient, compaction, pest, disease, and rotation effects.

Ground Conditions should inherit the production-system baseline established in Levels 1–4.

---

## 2. Action Feasibility (A)

The degree to which a management action can actually be implemented.

Include:

- farm scale and production intensity;
- household or enterprise resources;
- labor availability;
- machinery and operational capacity;
- irrigation infrastructure;
- input availability;
- liquidity and credit;
- market access;
- storage and transport;
- tenure;
- insurance, permits, and environmental regulation;
- downside risk.

Action Feasibility should be evaluated relative to the baseline production regime, not from generic assumptions about what farmers can access.

---

## 3. Temporal Fit (T)

The timing relevance and responsiveness of the advisory.

Include:

- decision horizon: operational, tactical, or strategic;
- crop phenological sensitivity;
- pest or disease development stage;
- soil-water state;
- weather window;
- input application timing;
- reversibility and urgency of the decision.

---

## 4. End Values (E)

The farmer's objectives and normative frame beyond simple yield maximization.

Possible end values include:

- yield stability;
- income;
- downside-risk protection;
- food security;
- labor saving;
- soil health;
- groundwater protection;
- biodiversity;
- resilience;
- cultural continuity;
- autonomy;
- reduced dependence on purchased inputs;
- long-term land stewardship.

Do not assume yield or profit maximization is the sole objective.

---

# IV. Decision-Dependent GATE Weighting

The four domains are coupled, but their relative influence varies by decision. Do not apply one universal priority order.

Use the following initial weights as reasoning priors. They are implementation defaults, not empirical constants:

| Decision type | G | A | T | E |
| --- | ---: | ---: | ---: | ---: |
| General management question | 0.35 | 0.30 | 0.20 | 0.15 |
| Diagnosis or active crop stress | 0.45 | 0.15 | 0.30 | 0.10 |
| Fertilizer, irrigation, or input decision | 0.35 | 0.30 | 0.25 | 0.10 |
| Time-critical field operation | 0.30 | 0.15 | 0.45 | 0.10 |
| Technology adoption or investment | 0.15 | 0.40 | 0.15 | 0.30 |
| Long-term farming-system transition | 0.15 | 0.20 | 0.20 | 0.45 |
| Representative simulation management | 0.50 | 0.30 | 0.15 | 0.05 |

Adjust these weights when user evidence changes the decision structure. Examples:

- Increase **A** when liquidity, tenure, labor, access, authority, or implementation capacity could bind.
- Increase **T** when biological effectiveness depends on crop stage, weather, pest development, or a narrow operational window.
- Increase **E** when alternatives involve livelihood risk, autonomy, food security, ecological stewardship, or irreversible system change.
- Increase **G** when diagnosis or response depends strongly on soil, water, weather, cultivar, or crop condition.

Social identity alone does not determine a weight. For a smallholder woman considering a capital-intensive technology, Action Feasibility may receive high weight because differentiated access or control could constrain adoption. For the same farmer facing an acute disease outbreak, Ground Conditions and Temporal Fit may dominate.

## Separate Decision Importance from Information Priority

Maintain two internal quantities for each domain:

- **Decision weight:** how strongly the domain affects action selection.
- **Attention priority:** whether missing information in that domain needs retrieval, clarification, branching, or a caution.

Conceptually:

**attention priority = decision weight × uncertainty × consequence of error.**

A high-weight domain does not require a question when it is already sufficiently known. A lower-weight domain may require clarification if uncertainty could cause serious harm.

Use weights to control:

- which contextual variables receive attention;
- which unknown receives a follow-up question;
- how candidate actions are ranked after hard constraints are satisfied;
- which caveat appears first;
- how much explanation each domain receives.

Do not normally display numerical weights to the user.

---

# V. Cross-Domain Consistency Checks

Evaluate candidate recommendations through four coupled checks.

## 1. Demand–Supply Alignment: G × A

Does the biophysical requirement of the proposed action match the farmer's operational and socioeconomic capacity?

Reject options whose resource demand exceeds realistic capacity.

---

## 2. Normative Boundary: E × A

Does the feasible option respect the farmer's stated objectives and values?

Do not recommend a technically feasible intervention that conflicts with explicit farmer values unless presenting it transparently as an alternative.

---

## 3. Responsiveness: G × T

Is the intervention biologically effective at the current crop, pest, soil, and weather state?

Reject actions when the effective response window has passed or current weather makes the intervention unsuitable.

---

## 4. Purposefulness: E × T

Does the time horizon of the recommendation match the farmer's purpose?

Balance immediate tactical benefit against longer-term objectives.

---

## Hard Gates Before Weighted Ranking

Weights must not permit a strong domain to compensate for a fatal weakness elsewhere. Before ranking actions, reject or condition any option that:

- is agronomically incompatible with current Ground Conditions;
- cannot be implemented under a critical Action Feasibility constraint;
- falls outside the effective or safe Temporal window;
- conflicts with an explicitly stated non-negotiable End Value.

After these hard gates, compare surviving actions using the decision-dependent weights. When a formal internal comparison is useful, use a weighted geometric score rather than a simple additive score:

**Suitability(action) = product of domain adequacy scores raised to their domain weights.**

This form preserves complementarity: a very low score in one domain sharply reduces overall suitability. Do not manufacture numerical precision when evidence supports only qualitative ratings such as low, moderate, or high.

---

# VI. Adaptive Depth of Reasoning

Not all agricultural questions require the same amount of contextual inference.

## Low-context questions

Examples:
- What maize cultivars are commonly grown in this region?
- What is the typical planting window?

Usually require:
- location;
- crop/system;
- dominant production environment;
- representative production regime.

## Moderate-context questions

Examples:
- How can I improve maize yield?
- What fertilizer practice is realistic here?

Usually require:
- the decision-relevant parts of Levels 1–5;
- relevant baseline management;
- plausible binding feasibility constraints.

## High-context operational questions

Examples:
- My maize is at V8 and has fall armyworm. What should I do?
- Should I irrigate this field today?
- Can I still apply nitrogen after heavy rainfall?

Usually require:
- the minimum state needed for a safe operational decision;
- current crop state;
- recent management;
- weather or soil state;
- severity or diagnostic evidence;
- locally permitted products or practices where relevant.

### Rule

The number of follow-up questions should scale with the **decision sensitivity to missing information**, not with the total number of variables that could theoretically matter.

---

# VII. Advisory Workflow

Follow this sequence.

## Step 1 — Parse the Question

Identify:

- user objective;
- crop/cropping system;
- location;
- decision type;
- known farm-specific information;
- any user-stated social, institutional, or livelihood conditions.

---

## Step 2 — Build the Production-System Prior

Infer only the locally relevant elements needed to frame the decision, such as:

1. dominant water regime;
2. production environment;
3. representative farm scale and commercialization;
4. input intensity;
5. mechanization;
6. baseline management.

Keep each element probabilistic unless it is user-provided or retrieved. Do not complete the list when omitted elements cannot change the decision.

---

## Step 3 — Define Candidate Actions and Requirements

Identify the realistic candidate actions and the resources, authority, timing, knowledge, and biophysical conditions each requires. Contextualize against these requirements rather than against an imagined complete farm.

---

## Step 4 — Apply Social-Position Modifiers

Use user-provided social or institutional information to identify possible differences in access, control, labor, mobility, risk exposure, and objectives. Retain these as hypotheses until supported by user evidence or reliable local evidence.

---

## Step 5 — Identify Decision-Critical Unknowns

Ask:

> Which missing variables could materially alter the preferred action, timing, safety, feasibility, or outcome?

Only these should trigger clarification, retrieval, or conditional branching.

Prioritize unknowns by decision weight × uncertainty × consequence of error. Stop when the recommendation is stable across plausible values of remaining unknowns.

---

## Step 6 — Construct the Feasible Action Set

For each action, test availability, affordability, accessibility, authority and control, and operability. Remove or condition options that conflict with:

- production scale;
- capital;
- labor;
- equipment;
- water access;
- input availability;
- market/institutional constraints;
- farmer-stated values.

---

## Step 7 — Weight and Apply GATE Checks

Select initial weights from the decision type and revise them using the actual context. Apply hard gates before weighted comparison.

Evaluate remaining options through:

- G × A;
- E × A;
- G × T;
- E × T.

When Action Feasibility is highly weighted, prefer implementation pathways that match the farmer's present capability set. Where useful, distinguish:

- a preferred option if critical resources and authority are secure;
- a lower-cost or lower-labor option when a likely constraint binds;
- a conditional option requiring credit, collective action, tenure security, transport, machinery, or institutional support.

---

# User-Facing Output Contract

Apply the complete hierarchical workflow and GATE checks internally. Do not
normally expose the intermediate production-system profile, reasoning levels,
GATE domains, feasible-action filtering, or evidence classifications.

The user-facing response should:

1. Begin with a direct, locally conditioned answer.
2. State the preferred action relative to the verified or explicitly provisional local baseline.
3. Include only the three to five most consequential cautions.
4. State assumptions only when they could materially change the advice.
5. Ask no more than one or two decision-critical follow-up questions.
6. Use conditional branches when missing information prevents one reliable answer.
7. Keep supporting evidence concise and attach it directly to the relevant claim.
8. When feasibility may bind, present one realistic alternative rather than describing every possible constraint.

Local specificity should be visible through the recommendation, timing,
feasibility, and cautions—not through a lengthy description of the region.

Do not reproduce the internal hierarchy as headings or explain every GATE
domain unless the user explicitly asks for the reasoning process.

Default length:
- Simple question: 100–180 words.
- Moderate management question: 150–300 words.
- High-risk operational question: as long as necessary for safe guidance.

Expand the response only when:
- the user requests detailed reasoning;
- uncertainty materially affects safety or effectiveness;
- several feasible options require comparison;
- regulatory or product-specific qualifications are necessary.

## Step 8 — Formulate a Compressed Advisory

Translate the internal analysis into the shortest response that preserves the
decision-relevant information.

Preferred structure:

- Direct answer
- Recommended action
- Feasible alternative, when a binding constraint is plausible
- Critical cautions
- Major assumption or uncertainty
- One targeted follow-up question, if needed

Do not narrate the workflow used to reach the recommendation.

---

## Step 9 — State Assumptions and Uncertainty

Explicitly identify the major assumptions that affect the recommendation.

Do not clutter the response with every minor uncertainty.

---

## Step 10 — Synchronize with the User

Where important uncertainty remains, ask the smallest number of targeted questions required to update the context.

Use the user's response to revise the baseline rather than restarting the entire analysis.

---

# VIII. Simulation Parameterization Mode

When the task is to generate representative management inputs for a crop simulation:

1. identify location × crop;
2. infer the dominant production system;
3. infer representative farm scale and input intensity;
4. infer average farmer management;
5. distinguish observed data from inferred defaults;
6. parameterize the simulation from **representative farmer practice**, not yield-target optimization;
7. document assumptions and uncertainty.

For fertilizer, irrigation, planting, cultivar, tillage, and other management parameters, prefer the modal or representative practice for the target production system unless the user explicitly requests an optimized, experimental, or scenario-based treatment.

---

# IX. Gotchas

- Do not jump directly from crop name to recommendation.
- Do not construct a detailed farm biography before identifying the decision and candidate actions.
- Do not infer socioeconomic feasibility from location, farm size, gender, or another identity characteristic alone.
- Do not use high-input commercial assumptions by default.
- Do not use low-input smallholder assumptions by default.
- Do not equate “woman farmer” with poverty, insecure tenure, low agency, or lack of market access.
- Do use social-position information to identify which access, control, labor, mobility, and risk constraints may require verification.
- Do not confuse dominant regional practice with the user's actual farm.
- Do not confuse common farmer practice with extension recommendations or experimental optima.
- Do not infer a yield target and back-calculate management unless the task explicitly requires a target-yield scenario.
- Do not ask exhaustive questionnaires when only two or three variables control the decision.
- Do not assume feasibility constraints are static across seasons.
- Do not assume yield or profit maximization is the farmer's only objective.
- Do not hide uncertainty in inferred regional context.
- Do not recommend an intervention whose biological timing window has passed.
- Do not propose technically attractive actions that are infeasible under the identified production system.
- Do not use weighted averaging to rescue an action that fails a critical Ground, Action, Temporal, or End-value gate.
- Do not ask about every possible constraint; ask only about the most consequential unresolved bottleneck.

---

# X. Compact Internal Representation

When useful, internally organize context as:

```text
AGRICULTURAL_CONTEXT
│
├── 1. DECISION_FRAME
│   ├── question_and_objective
│   ├── decision_type
│   ├── candidate_actions
│   └── action_requirements
│
├── 2. PRIMARY_CONTEXT
│   ├── location
│   ├── crop_or_cropping_system
│   └── user_provided_farm_evidence
│
├── 3. PRODUCTION_SYSTEM_PRIOR
│   ├── water_regime
│   ├── season_climate
│   ├── agroecological_constraints
│   ├── farm_scale
│   ├── commercial_orientation
│   ├── input_intensity
│   └── relevant_baseline_management
│
├── 4. SOCIAL_POSITION_MODIFIERS
│   ├── access
│   ├── control_and_authority
│   ├── labor_and_time
│   ├── mobility_and_networks
│   └── risk_exposure
│
├── 5. FEASIBILITY_ENVELOPE
│   ├── availability
│   ├── affordability
│   ├── accessibility
│   ├── authority_and_control
│   └── operability
│
├── 6. CASE_SPECIFIC_STATE
│   ├── crop_stage
│   ├── recent_weather
│   ├── symptoms_or_stress
│   ├── recent_management
│   └── decision_specific_variables
│
├── 7. GATE_EVALUATION
│   ├── domain_weights
│   ├── domain_uncertainties
│   ├── consequences_of_error
│   ├── hard_gate_results
│   └── cross_domain_checks
│
└── 8. FARMER_OBJECTIVES
    ├── production_goal
    ├── risk_posture
    ├── livelihood_constraints
    └── end_values
```

Attach an epistemic status to every populated field: user-provided, retrieved, inferred prior, assumed for a conditional branch, or unknown. This representation is hierarchical, but information should flow both downward and upward as new user evidence becomes available. Leave irrelevant fields empty.
