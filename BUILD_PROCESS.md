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
