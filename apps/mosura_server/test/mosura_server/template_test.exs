defmodule MosuraServer.ProjectTest do
  use ExUnit.Case, async: true

  alias MosuraServer.{Project, Ticket}

  setup do
    project = start_supervised!(Project)
    %{project: project}
  end

  test "stores tickets by id", %{project: project} do
    ticket = %Ticket{id: "1234"}
    assert :error = assert(Project.get(project, ticket.id))

    assert :ok = Project.put(project, ticket)
    assert {:ok, ^ticket} = Project.get(project, ticket.id)
  end
end
