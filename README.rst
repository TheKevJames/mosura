Mosura
======

Mosura is an opinionated Task management frontend. Overall project goals are:

* **usage agnostic**: team members using Mosura should not conflict with those
  who do not
* **minimal views**: if you don't use a feature, it shouldn't bloat your
  interface or slow you down
* **opinionated workflows**: Mosura assumes you're looking for a simplified
  experience and trims out all the inessential cruft

Hacking
-------

You'll need to `configure yourself a Jira connection`_ before being able to run
Mosura. For now, Mosura requires you select a single Jira project to follow:

.. code-block:: console

    export JIRA_DOMAIN=https://myinstance.atlassian.net
    export JIRA_USERNAME=mosura@thekev.in
    export JIRA_TOKEN=FooBaR123!
    export JIRA_PROJECT=MOS

Useful commands:

.. code-block:: console

    # install dependencies
    poetry install

    # run tests
    poetry run pytest

    # run dev server (localhost:8000)
    poetry run uvicorn mosura.app:app --reload

TODO: fixup docker build

Workflow Assumptions
--------------------

We make the following assumptions about your workflow / project setup. Note
that much of this section also doubles as a "TODO: make these configurable"
list.

Overall, we assume your project is configured at minimum with the following
fields:

* ``key``: eg. ``MOS-123``
* ``summary``: the short title of the ticket
* ``description``: the long-form body of the ticket
* ``status``: the current status of the ticket

  * if you use a ``Needs Triage`` value, it will get highlighted as requiring
    attention in the issue list and coloured red in the Gannt chart
  * ``In Progress`` or ``Code Review`` will get coloured yellow in the Gannt
    chart
  * ``Closed`` will be red on the chart and will not be visible anywhere else

* ``priority``: the determined priority of the ticket

  * ``Low``, ``Medium``, ``High``, and ``Urgent`` will get special icons

* ``assignee``: the assigned user

  * if the ``assignee`` matches your configured Jira credentials, the "my
    issues" page will work

* ``customfield_12161``: a.k.a. ``Start Date``; if anyone is aware of a builtin
  version of this, I'd love to switch over

  * if a ticket's start date is within the current quarter and it also has a
    time estimate, it will get drawn onto the Gannt chart

* ``Original estimate``: the time estimate for the ticket

  * if a ticket has this set along with a start date, it will get drawn onto
    the Gannt chart

* ``components``: arbitrary list of components

  * if a ticket has no listed components, it will get highlighted as requiring
    attention

* ``labels``: arbitrary list of labels

  * if a ticket has no listed labels, it will get highlighted as requiring
    attention
  * if the label matches ``$JIRA_LABEL_OKR`` (default: ``okr``), include it in
    the shortlist of "issues that need scheduling" on the Gannt page

We also assume that you are interested in quarterly planning, using the
financial quarter model starting on February, eg. Q1 starts on February 1st and
the quarter's year is the one that Q4 will fall in (so 2022-02-01 is 2023Q1).

.. _configure yourself a Jira connection: https://id.atlassian.com/manage-profile/security/api-tokens
