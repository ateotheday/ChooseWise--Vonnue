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


**Issues encountered:** the modelintroduces too much latency during extraction.
