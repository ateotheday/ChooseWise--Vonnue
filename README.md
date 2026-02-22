A web-based application built as part of a take-home assessment conducted by Vonnue.
The system helps users choose between multiple options by evaluating them against weighted criteria and producing an explainable ranked recommendation. 

This is a basic implementation of the system I am building :

![USER REGISTRATION](https://github.com/user-attachments/assets/02ef1c92-175b-4203-90f0-d6395655fd70)

Here,
The user enters the website, and a small personality quiz is taken, which analyzes traits such as :
 -Risk tolerance (1–5 scale)
 -Budget sensitivity (1–5 scale)
 -Long-term focus (1–5 scale)
 -Analytical vs Emotional (1–5 scale)
 -Convenience vs Performance (1–5 scale)
Accordingly, weights will be adjusted.
These are used for default weight assignment.


(1) When the user enters the decision question :
It is passed to an LLM only for extracting the important details required for later evaluation. 
Then the user may add options, or the user can ask the system to provide options. 
The extracted details are passed to the RAG module, which retrieves relevant options from a curated knowledge base.
Similarly, for criteria selection, the user can either define criteria manually or allow the system to suggest relevant evaluation criteria using RAG.
This feature is included to provide convenience.

(2)
The system  converts the options into a structured evaluation format.
Each option is represented as a vector of values corresponding to the selected criteria. If there are  n criteria and  m options,
The system constructs a decision matrix of size :
𝑚 × 𝑛
m×n, where each row represents an option, and each column represents a criterion.
The processed and normalized matrix is then passed to the weighting and ranking engine for final evaluation.
This is the base idea of the website..


(3)
In the weight assignment part,
 Users specify the criteria and assign them a score on a scale of 1 to 10. These values, along with the personality quiz scores, which hold only a small part of the total weight, are added together to get the final score for each of the options. 
 These are evaluated based on the data from the RAG systems. Then the weights are normalized.
Personality profiling is used to generate a starting set of default weights when the user is unsure or chooses system-defined criteria.
These defaults are derived from decision-relevant traits such as budget sensitivity, risk tolerance, etc. 
If the user manually adjusts weights, the system treats user input as higher priority and reduces the influence of personality-based defaults, ensuring the final decision reflects the user’s current intent.

(f)
 After scoring, the system ranks all options based on their final weighted scores. 
 The option with the highest score is displayed as the recommended choice.
 Along with the result, the system provides a brief explanation describing why this option was chosen. 
 The explanation highlights the most influential criteria, the applied weights, and any key trade-offs observed during evaluation. 
