i just need a dashboard. Dont make a app. Only simple dashboard for following:
Main frontend goal
The dashboard is not where most daily work happens.
The dashboard is for:
setup
visibility
team management
token creation
audit logs
The CLI is for:
push
pull
run
day-to-day dev work
So the dashboard should feel like the control center, not the main workflow.
Core design principle
Use a layout like this:
Sidebar on left
Main content on right
Top bar for project/environment switching
Keep it clean, similar to:
Supabase
Vercel
GitHub settings
Linear style simplicity
Avoid making it look like:
AWS console
complex SIEM dashboard
overloaded admin panel
Dashboard information architecture
I’d structure it like this:
Sidebar
Projects
Overview
Secrets
Environments
Team
Runtime Tokens
Audit Logs
Settings
If user is outside a project:
Home
Projects
Account
If inside a project:
Overview
Secrets
Environments
Team
Runtime Tokens
Audit Logs
Settings
That is enough for MVP.
Pages you need
A. Auth pages
Simple and clean:
Sign up
Log in
Fields:
email
password
Later:
forgot password
magic link
GitHub auth
Keep MVP basic.
B. Projects page
This is the landing page after login.
Show:
list of projects
create new project button
project cards
Each project card can show:
project name
number of environments
number of members
last activity
CTA:
Create Project
This page should feel like:
“Pick what team/app you want to manage.”
C. Project overview page
This is the most important dashboard page.
When user clicks a project, show:
Top section
project name
current environment
quick actions:
Create runtime token
Invite teammate
View secrets
View CLI commands
Summary cards
number of secrets
number of environments
number of members
active runtime tokens
last updated time
Activity feed
Recent events:
Abdul pushed secrets to dev
Sarah pulled prod
runtime token created
token used by app
teammate invited
CLI quickstart box
Show commands like:
envbasis login
envbasis push
envbasis pull
This is very important. Your users are developers, so surface the terminal flow directly in the UI.
D. Secrets page
This should be one of the main pages.
What to show
A table:
Key Name
Environment
Version
Last Updated
Updated By
Actions
Example:
Key Env Version Updated By
OPENAI_API_KEY dev 3 2h ago Abdul
Do not show raw values by default.
Actions:
reveal temporarily
copy
edit
delete
For MVP, revealing can require clicking a button and showing warning text.
Also include
Add secret manually
Bulk upload .env
Search secrets
Filter by environment
This page should feel like:
“Here are my project secrets without exposing them all the time.”
E. Environments page
Very simple page.
Show:
dev
staging
prod
For each environment:
number of secrets
last updated
runtime tokens count
Actions:
create environment
rename later
maybe delete later
This page helps people mentally separate environments.
F. Team page
Show project members.
Columns:
Name / Email
Role
Joined
Last activity
Actions
Actions:
invite member
revoke access
For MVP roles can be:
Owner
Member
No need for complex RBAC yet.
Invite flow:
email input
send invite
G. Runtime Tokens page
This page is very important because this is your sensitive admin area.
Show
token name
environment
created by
expires at
last used
status
Actions:
create token
revoke token
Create token modal
Fields:
token name
environment
expiry
permission fixed as read-only for MVP
After creation:
show token once
warning message:
“Copy this token now. You will not be able to see it again.”
This page should feel deliberate and secure.
H. Audit Logs page
Show an event stream.
Columns:
Time
Actor
Action
Environment
Details
Examples:
Abdul pushed secrets to dev
Fatima pulled secrets from prod
Runtime token created
Token revoked
Member invited
Filters:
action type
environment
actor
date range later
This gives trust to the platform.
I. Settings page
Minimal for MVP.
Sections:
project name
delete project later
environment defaults later
security preferences later
Can stay very small.
Best UI flow for first-time users
When a new user creates a project, guide them through setup.
Onboarding flow
Step 1: Create project
Step 2: Create environment
Step 3: Push your .env from terminal
Step 4: Invite teammate or create runtime token
This can be shown as a checklist on the overview page.
Example:
Create first environment
Push your first .env
Create runtime token
Invite your first teammate
This is very good for activation.
Visual style
Since this is a dev tool, keep it:
dark mode friendly
minimal
clean cards
monospace for commands
subtle color accents
Use:
lots of whitespace
clear tables
strong headings
small code blocks for commands
Color approach:
neutral dark or neutral light
green for success
yellow for warnings
red for revoke/delete
blue or purple for actions
Avoid too many gradients or flashy startup visuals.
It should feel trustworthy.
Components you’ll need
Frontend component list:
Shared
Sidebar
Top navbar
Project switcher
Environment selector
Search bar
Table component
Empty state component
Modal
Confirm dialog
Code block component
Activity feed item
Status badge
Specific
Secret row
Token row
Audit log row
Team member row
Project card
Important UX rules
Rule 1
Always show the related CLI command where useful.
For example on secrets page:
envbasis push
envbasis pull
Rule 2
Never expose secrets casually.
Show names by default, values only on explicit reveal.
Rule 3
Make runtime tokens feel sensitive.
Warnings, one-time display, revoke button.
Rule 4
Use human wording.
Say:
Project
Environment
Member
Token
Push
Pull
Not:
principal
policy engine
scoped access credential manifest
Rule 5
Design for small teams first.
The UI should feel great for 1 to 10 people.
My strongest recommendation
Your dashboard should answer these questions instantly:
What project am I in?
Which environment am I viewing?
How many secrets are there?
Who has access?
What tokens exist?
What happened recently?
What command do I run next?
If the UI answers those well, the product will feel sharp.
Recommended palette
Use white + beige + neutral gray + one accent color.
Example palette:
Background
White: #FFFFFF
Soft background / panels
Beige: #F5F1EA
Borders / subtle UI
Light gray: #E5E5E5
Text
Dark charcoal: #1F1F1F
Accent color (important!)
Deep blue or purple
Example:
Blue accent
#4F46E5
or
Purple accent
#7C3AED
How it should look in UI
Sidebar
Beige background:
#F5F1EA
Main dashboard area
White:
#FFFFFF
Cards / tables
White with light border:
border: #E5E5E5
Buttons
Accent color:
Primary button: #4F46E5
Text: white
Why this works
You get:
clean developer UI
premium feel
not too dark
not too playful
still technical
Many modern tools do similar:
Linear
Vercel
Raycast
Supabase (light theme)
Important tip
Do NOT make beige too strong.
Bad:
#E0C9A6
Too warm.
Good:
#F5F1EA
#F7F5F2
Very subtle.
Perfect balance for EnvBasis
Use:
White #FFFFFF
Beige #F5F1EA
Gray border #E5E5E5
Text #1F1F1F
Accent #4F46E5
This gives a clean dev tool aesthetic.
My honest opinion
For developer products, the safest palette is:
White
Light gray
Charcoal text
One strong accent
