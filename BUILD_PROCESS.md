day #1  [23/02/2026]

I initially planned on designing the website by only considering a quiz, which is responsible for all the decisions that the system would make. But later I found it to be too shallow. 
Hence, I reconsidered and decided to make the initial quiz results the base weights. 
They do hold significance in cases where the user doesn't want to consider options or doesn't have options or constraints. Also, they do influence the overall decision to an extent.

During development, I considered using MySQL since I had XAMPP installed and it would simulate a production-style database setup.
 However, after evaluating further, I decided to use SQLite. As it does not require a separate database server, and for portability.


I have made :
-The landing page.


-Login and register routes.


-SQLite database integration.




Mistakes encountered :
-While making the login page,
  If the user entered the wrong credentials, the page just reloaded. No error message was displayed. 
This error was corrected by :
Implementing flash messages to display error feedback to the user.




day #2 [24/02/26]


Today I,

Connected Quiz to Backend (app.py)


Configured POST handling


Extracted form inputs using request.form


Stored weights in session


Redirected to the dashboard after completion

The quiz is set up in such a way that when a person logs in, they have to take the quiz to form the base weights. Then, when they log in again, they will be redirected to the dashboard only.


A person table was created to handle user authentication and to manage the onboarding flow. Along with the usual login fields like email, password hash, and role, I added a quiz_completed flag to control whether the user has finished the preference quiz.

When a user logs in, the backend checks this flag. If the user hasn’t completed the quiz yet, they are redirected to the quiz page. If they have already completed it, they are taken directly to the dashboard.

Once the quiz is submitted, the system updates the quiz_completed field in the database. This ensures that the quiz is only shown once and the user experience remains smooth during future logins.

Issues encountered :


Even after completing the quiz, logging in still led to the quiz again.
I figured the problem is probably because the profiles table is not getting updated.

