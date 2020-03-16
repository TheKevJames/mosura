defmodule MosuraServer.Project do
  require Logger
  use GenServer

  @doc """
  Starts a new project.
  """
  def start_link(opts) do
    GenServer.start_link(__MODULE__, :ok, opts)
  end

  @doc """
  Gets a ticket from the `project` by `id`.

  Returns `{:ok, ticket}` if the ticket exists, `:error` otherwise.
  """
  def get(project, id) do
    GenServer.call(project, {:get, id})
  end

  @doc """
  Puts the `ticket` in the `project`.
  """
  def put(project, ticket) do
    GenServer.cast(project, {:put, ticket})
  end

  @impl true
  def init(:ok) do
    {:ok, %{}}
  end

  @impl true
  def handle_call({:get, id}, _from, tickets) do
    {:reply, Map.fetch(tickets, id), tickets}
  end

  @impl true
  def handle_cast({:put, ticket}, tickets) do
    {:noreply, Map.put(tickets, ticket.id, ticket)}
  end
end
