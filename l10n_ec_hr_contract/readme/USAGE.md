Contract states are computed from dates. A daily cron updates them.

* Draft: the contract has no start date.
* Trial / Trial ending: the trial period is running (ends within 10 days for "Trial ending").
* Open: the contract is running.
* Contract ending / Pending closure: the end date is within 30 days / has passed.
* Completed: the version is archived.

The trial end date is computed from the start date and the number of trial days configured in Settings.
