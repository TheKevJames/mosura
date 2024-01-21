Mosura
======

Mosura is an opinionated Task management frontend. Overall project goals are:

* **usage agnostic**: team members using Mosura should not conflict with those
  who do not
* **minimal views**: if you don't use a feature, it shouldn't bloat your
  interface or slow you down
* **opinionated workflows**: Mosura assumes you're looking for a simplified
  experience and trims out all the inessential cruft

I don't currently expect Mosura to be useful for anyone but myself. Maybe
eventually!

Usage
-----

First off, you'll need to `create a Jira API token`_.

Best run via docker/podman/etc:

.. code-block:: console

    docker run -d \
        --name=mosura \
        -p 8080:8080 \
        -v /path/to/appdata:/data \
        -e JIRA_DOMAIN=https://myinstance.atlassian.net \
        -e JIRA_AUTH_USER=myuser@example.com \
        -e JIRA_AUTH_TOKEN=mytoken123456 \
        -e JIRA_PROJECT=MOS \  # TODO: comma-separated list
        -e JIRA_LABEL_OKR=okr \  # (optional, default: okr)
        -e MOSURA_APPDATA=/data \  # (optional, default: .)
        -e MOSURA_PORT=8080 \  # (optional, default: 8080)
        -e MOSURA_HEADER_USER_EMAIL=X-Token-User-Email \
        --restart unless-stopped \
        quay.io/thekevjames/mosura:latest

# TODO: docker-compose, k8s

Can also be run locally for development purposes:

.. code-block:: console

    export ...
    export MOSURA_USER=...  # force the user without going through auth
    poetry install --sync
    poetry run uvicorn mosura.app:app --reload

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
    attention in the issue list and coloured red in the timeline
  * ``In Progress`` or ``Code Review`` will get coloured yellow in the timeline
  * ``Closed`` will be red on the chart and will not be visible anywhere else

* ``priority``: the determined priority of the ticket

  * ``Low``, ``Medium``, ``High``, and ``Urgent`` will get special icons

* ``assignee``: the assigned user

  * if the ``assignee`` matches your configured Jira credentials, the "my
    issues" page will work

* ``customfield_12161``: a.k.a. ``Start Date``; if anyone is aware of a builtin
  version of this, I'd love to switch over
* ``Original estimate``: the time estimate for the ticket

  * if a ticket has a start time and a time estimate, and that timespan is
    close to the current date (between a couple weeks in the past and a couple
    months in the future), it will get drawn onto the timeline

* ``components``: arbitrary list of components

  * if a ticket has no listed components, it will get highlighted as requiring
    attention

* ``labels``: arbitrary list of labels

  * if a ticket has no listed labels, it will get highlighted as requiring
    attention
  * if the label matches your configured "OKR Label" setting (default:
    ``okr``), ensure it appears on the timeline page

* ``votes``: the collection of user votes on the issue

.. _create a Jira API token: https://id.atlassian.com/manage-profile/security/api-tokens
