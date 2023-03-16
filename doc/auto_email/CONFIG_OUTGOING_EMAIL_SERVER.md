# Scheduled task for send email of electronic documents

## Important

- The sending is not immediately, you wait for other schedule task that name is "Email
  Queue Manager"

## Configure Outgoing Mail Servers

- Settings -> Discuss
- Active Custom Email Servers
- In option Outgoing Mail Servers, create your configuration

## Configure bounce

- Settings -> Technical -> Parameters -> System Parameters
- Search bounce
- Edit mail.bounce.alias, set your name of email address
- Edit in preferences of your user the email
- Test Connection in Outgoing Mail Servers

## View scheduled task

- Settings -> Technical -> Automation -> Scheduled Actions
- Open "Send email with authorized electronic documents"

## View email template

- Settings -> Technical -> Emails -> Email Templates
- Open "Invoice: Send by email" , in Email Configuration -> From, verify or set email
  address

## Before test the task

- Push "Send & Print" to configure your custom layout in electronic document
