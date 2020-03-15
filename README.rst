Mosura
======

Goals
-----

The goal of Mosura is to be an all-in-one interface to other task management
utilities, eg. by allowing users to use Mosura to interface with their existing
Jira/Github/taskwarrior/etc backends in a single, integrated fashion.

* [ ] implicit equivalence: any entity in another system should have a
      representation in Mosura
* [ ] bi-directional sync: some team members should be able to use Mosura while
      others use a different solution with no conflicts
* [ ] minimal views: if you don't use a feature, it shouldn't bloat your
      interface
* [ ] pre-built roles: getting off the ground with Mosura should be
      straightfoward, customization should be opt-in

Data Model
----------

::

    Ticket:
        id: String
        name: String
        status: Enum
        assignee: [User]
        meta: [Meta]
        tags: [Tag]
        refs: [{ticket: Ticket, kind: RefKind}]  # split parent vs blocker?
        log: [Comment | Event | ...]
        ...
    GithubIssue implements Ticket:
        id = owner <> repo <> str(id)
        status = open | closed
        ...
    JiraStory implements Ticket:
        id = instance <> str(id)
        status = convert(JiraStory.status -> Ticket.status)  # user config
        ...
    JiraEpic implements Ticket:
        id = instance <> str(id)
        refs.validate = all(refs, fn({_, kind}) -> kind != :parent} end)
        ...

    Tag:
        id: String
        name: String
    GithubLabel implements Tag:
        id = owner <> repo <> name
        name = name

    Meta:
        id: String
        name: String
        value: Any
    Priority implements Meta:
        id = ...
        name = "Priority"
        value = :low | :medium | :high | ...
    Reporter implements Meta:
        id = ...
        name = "Reporter"
        value = User
