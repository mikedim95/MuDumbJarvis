import React from 'react';
import {createRoot} from 'react-dom/client';
import '@xyflow/react/dist/style.css';
import '@xterm/xterm/css/xterm.css';
import 'vis-timeline/styles/vis-timeline-graph2d.min.css';
import './styles.css';
import App from './App.jsx';

class WorkspaceBoundary extends React.Component{
 state={error:null};
 static getDerivedStateFromError(error){return {error};}
 render(){return this.state.error?<aside className="csi-workspace" role="alert" style={{padding:32}}>
  <h2>CSI interface unavailable</h2><p>The existing HUD is still available.</p>
  <button onClick={()=>{localStorage.removeItem('jarvis-csi-open');location.reload();}}>RETURN TO HUD</button>
 </aside>:this.props.children;}
}
createRoot(document.getElementById('csiRoot')).render(<WorkspaceBoundary><App/></WorkspaceBoundary>);
