**2. Evolution of Thinking**


Phase 1: Pure Deterministic System


My early assumption was:


“All decision-making can be handled using structured input and scoring.”


However, I quickly realized:


Users often enter vague or unstructured questions.


Real-world decisions require contextual knowledge.


Manually defining all criteria per decision is inefficient.


This led me to integrate LLM-based extraction.



Phase 2: Full LLM-Based Decision Making **(Rejected)**



At one point, I considered letting the LLM:



Generate options.

Generate criteria.

Rank options.

Provide reasoning.


This approach felt powerful but not reliable.



Phase 3: Hybrid Architecture (Final Design)


I refined the architecture into three layers:


**LLM → Extraction Only**



**RAG → Domain Knowledge Retrieval using pre-defined Knowledge bases**



**Engine → Deterministic Scoring after llm parses through the kb**




**day #1  [23/02/2026]**

I initially planned on designing the website by only considering a quiz, which is responsible for all the decisions that the system would make. But later I found it to be too shallow. 
Hence, I reconsidered and decided to make the initial quiz results the base weights. 
They do hold significance in cases where the user doesn't want to consider options or doesn't have options or constraints. Also, they do influence the overall decision to an extent.

During development, I considered using MySQL since I had XAMPP installed and it would simulate a production-style database setup.
 However, after evaluating further, I decided to use SQLite. As it does not require a separate database server, and for portability.


I have made :

**-The landing page.**


**-Login and register routes.**


**-SQLite database integration.**




Mistakes encountered :
-While making the login page,
  If the user entered the wrong credentials, the page just reloaded. No error message was displayed. 
This error was corrected by :
Implementing **flash messages** to display error feedback to the user.




**day #2 [24/02/26]**


Today I,

**Connected Quiz to Backend** (app.py)


**Configured POST handling**


**Extracted form inputs using request.form**


**Stored weights in session**


**Redirected to the dashboard after completion**

The quiz is set up in such a way that when a person logs in, they have to take the quiz to form the base weights. Then, when they log in again, they will be redirected to the dashboard only.


A person table was created to handle user authentication and to manage the onboarding flow. Along with the usual login fields like email, password hash, and role, I added a quiz_completed flag to control whether the user has finished the preference quiz.

When a user logs in, the backend checks this flag. If the user hasn’t completed the quiz yet, they are redirected to the quiz page. If they have already completed it, they are taken directly to the dashboard.

Once the quiz is submitted, the system updates the quiz_completed field in the database. This ensures that the quiz is only shown once and the user experience remains smooth during future logins.

**Issues encountered:**


Even after completing the quiz, logging in still led to the quiz again.
I figured the problem is probably because the profiles table is not getting updated.


Solution :
To ensure users complete the personality quiz only once, **conditional routing logic** was implemented.

After login, the system checks whether a profile entry exists in the profiles table.

If a profile exists → the user is redirected to the **dashboard.**

If not → the user is redirected to the **quiz page**.


**Day #3 [26/02/2026]**

Architectural diagram for score calculation :



<img width="2060" height="426" alt="mermaid-diagram" src="https://github.com/user-attachments/assets/a617743d-889b-49d9-af46-1371f3d99098" />



First, the base weights from the personality quiz are normalized so that:


Sum of w_j = 1



This ensures that the total importance across all criteria equals 1.



When the user enters a decision problem, the LLM is used only to extract structured details. It does not make the decision.



Next, I construct a decision matrix:



**X = [x_ij]**



where:


x_ij = value of option i under criterion j



Since different criteria may use different units (price, rating, performance), I normalize them to a 0–1 scale.



For benefit criteria (higher is better):



**r_ij = (x_ij − min(x_j)) / (max(x_j) − min(x_j))**



For cost criteria (lower is better):



**r_ij = (max(x_j) − x_ij) / (max(x_j) − min(x_j))**



After normalization, all values lie between 0 and 1.



Finally, the score for each option is calculated as:




S_i = Sum (w_j × r_ij)






Final Score = Add up (Weight × Normalized Value)



The option with the highest score is selected and displayed along with the reason for choosing.



**Day #4 [27/02/2026]**


I worked on the Decision page UI.

**Day #5 [28/02/2026]**

Today,


I worked on the decision page. 


The decision table was made for storing the decision text by the user, options, and criteria.


I installed ollama to use a model for extracting the important details from the decision text.

### Key Work Completed


- Integrated a local LLM pipeline using **Ollama (llama3)** for structured extraction of decision context.

- Implemented schema-constrained JSON extraction to ensure:
  
  - No hallucinated fields
 
    
  - Safe parsing 

- Connected the extraction layer to the `/decision/submit` route so that every decision submission now:

  
  1. Extracts structured metadata
 

  2. Stores it in the database
 
 
  3. Persists user-defined options and criteria
 
  

### Architectural Insight

The LLM is used strictly for structured parsing of user input.  


Final scoring and ranking remain deterministic and rule-based to avoid black-box decision-making.


So, it extracts only important details...


**{
  "extracted": {
    "constraints": [],
    "decision": "",
    "decision_type": 
    "entities": 
    "goal": 
    "preferences": 
    "risk_level": 
    "time_horizon":
  },
  "question": "-"
}**

This is the final extracted file. It includes a decision type and some other constraint details extracted from the user's decision text.


**Issues encountered:** The model introduces too much latency during extraction.


**#day 6 [01/02/2026]**

Today I worked on the main parts.

-when the user enters a decision text and submits it along with the options and criteria,

The llama model, which runs locally on my device, is given a prompt to return the extracted text from it. It is also told to categorise the decision into a particular decision type.This is already pre-defined and given as prompt to the model. After extracting it gives the reults back as json and is stored with a decision id.



issues encountered :  Criteria Importance Placement 

Confusion:


I was unsure whether to:


Collect importance weights for each criteria on a separate page


Or collect them directly below the criteria input


**Final Decision:**


I kept the importance scale on the same page, directly below the criteria.


**Reason:**


Keeps user context intact


Avoids unnecessary page transitions




**2️ .Generic vs Specific RAG Knowledge Base**


Initial Idea:

I wanted to build a detailed RAG knowledge base including:



Specific laptop models



Detailed specifications



Product-level comparisons



However, this created a problem:



If a user enters:



“MacBook Pro M3 vs Dell XPS 13”



And those exact models are not in the KB:



Retrieval would fail



Scoring would break



System becomes hardcoded and fragile



**Final Decision:**



Instead of storing product-specific knowledge, I:



Built **generic domain-based KBs**



Focused on decision frameworks (e.g., performance, budget, durability)



Let the LLM reason over user-provided options using domain guidance



**3️. Why Not Let the User Score Each Option?**


Initially, I questioned:


If the user is confused, why ask them to score each option?



If the user already knew how to score each option precisely,


Then they wouldn't need the system.



**Final Approach:**

The retriever extracts domain-relevant criteria.


The scoring engine applies weights.


The LLM assists in structured evaluation when necessary.




**5️. RAG Retrieval Overhead**

While experimenting with full RAG vectorization:

Embedding creation was computationally heavy

Local **LLM timeouts occurred**


Retrieval felt static and hardcoded

I realized full vector-based RAG was unnecessary for the scope.



Change Made:

Rebranded to:


**“LLM-assisted retrieval from structured domain KB”**




**6️. Issue: All Options Ranked as 3**

During testing:

All options received the same score.

Investigation:

Root cause was:

**LLM timeout during extraction**

**Insufficient KB context returned**

Fallback values defaulting to neutral scores

Fixes:

Reduced the extraction prompt size


 By,
   -reducing timeout

   
   -increasing tokens
   


**Added fallback validation**


After optimization, scoring stabilized.



..... 
The results are retrieved very slowly



. This was caused by the extraction and then parsing through the kb.


**It was overkill, and could be reduced by combinig both of them into a single stage rather than separately.**
