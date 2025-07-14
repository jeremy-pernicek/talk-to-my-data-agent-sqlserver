import './App.css';
import Pages from './pages';
import { useDataRobotInfo } from './api/user/hooks';

function App() {
  useDataRobotInfo();

  return <Pages />;
}

export default App;
