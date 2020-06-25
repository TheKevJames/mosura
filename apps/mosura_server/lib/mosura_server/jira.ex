# TODO: extend from MosuraServer.Ticket
defmodule MosuraServer.JiraTicket do
  require Logger
  use GenServer

  def start_link(opts) do
    GenServer.start_link(__MODULE__, opts[:key])
  end

  @impl true
  def init(key) do
    send(self(), :pull)
    {:ok, %MosuraServer.Ticket{id: key}}
  end

  # client
  def get(ticket) do
    GenServer.call(ticket, :get)
  end

  # server
  @impl true
  def handle_call(:get, _from, data) do
    {:reply, data, data}
  end

  @impl true
  def handle_info(:pull, data) do
    base_url = Application.get_env(:mosura_server, :jira_url)
    headers = []
    options = [
      hackney: [
        basic_auth:
          {Application.get_env(:mosura_server, :jira_user),
           Application.get_env(:mosura_server, :jira_api_token)},
        follow_redirect: true
      ]
    ]

    url = base_url <> <<"/rest/api/3/issue/">> <> data.id <> <<"?fields=summary">>

    with {:ok, %{body: body, status_code: 200}} <- HTTPoison.get(url, headers, options),
         {:ok, %{"fields" => %{"summary" => summary}}} <- Poison.decode(body) do
      {:noreply, Map.put(data, :name, summary)}
    end
  end
end

# TODO: extend from MosuraServer.Project
defmodule MosuraServer.JiraProject do
  require Logger
  use GenServer

  # client
  def start_link(opts) do
    GenServer.start_link(__MODULE__, :ok, opts)
  end

  @impl true
  def init(:ok) do
    base_url = Application.get_env(:mosura_server, :jira_url)
    project = Application.get_env(:mosura_server, :jira_project)
    headers = []
    options = [
      hackney: [
        basic_auth:
          {Application.get_env(:mosura_server, :jira_user),
           Application.get_env(:mosura_server, :jira_api_token)},
        follow_redirect: true
      ]
    ]

    # TODO: pagination
    url = base_url <> <<"/rest/api/3/search?fields=key&jql=project=">> <> project

    with {:ok, %{body: body, status_code: 200}} <- HTTPoison.get(url, headers, options),
         {:ok, %{"issues" => issues}} <- Poison.decode(body),
         keys <- Enum.map(issues, fn i -> i["key"] end) do
      # TODO: mosura ticket IDs instead of Jira IDs
      {:ok,
       %{
         tickets:
           Enum.reduce(keys, %{}, fn k, acc ->
             child_spec = {MosuraServer.JiraTicket, [key: k]}
             case DynamicSupervisor.start_child(MosuraServer.JiraSupervisor, child_spec) do
               {:ok, pid} -> Map.put(acc, k, pid)
               {:error, err} -> Logger.error(inspect err)
             end
           end)
       }}
    end
  end

  def get(project, id) do
    GenServer.call(project, {:get, id})
  end

  def list(project) do
    GenServer.call(project, {:list})
  end

  # def put(project, ticket) do
  #   GenServer.cast(project, {:put, ticket})
  # end

  @impl true
  def handle_call({:get, id}, _from, data) do
    case Map.fetch(data[:tickets], id) do
      {:ok, pid} -> {:reply, MosuraServer.JiraTicket.get(pid), data}
      :error = err -> {:reply, err, data}
    end
  end

  @impl true
  def handle_call({:list}, _from, data) do
    {:reply, Map.keys(data[:tickets]), data}
  end

  # @impl true
  # def handle_cast({:put, ticket}, _from, data) do
  #   {:noreply, Map.put(data[:tickets], ticket.id, ticket)}
  # end
end
